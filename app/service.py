"""Application service layer: tenant isolation, idempotency, WA valuation, and audit."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.catalog import render_catalog
from app.creative import (
    BUILTIN_ASSET_MAP,
    DEFAULT_ASSETS_DIR,
    LICENSED_LOCAL_ASSETS,
    SUPPORTED_EXPORT_FORMATS,
    compute_draft_revision_hash,
    encode_png_rgb,
    load_and_verify_asset,
    render_poster_artifact,
    validate_export_request,
    validate_poster_draft_input,
    validate_preview_request,
)
from app.db import (
    DEFAULT_DB_PATH,
    DatabaseConfig,
    PostgresPoolManager,
    db_transaction,
    resolve_db_config,
)
from app.domain import (
    DEFAULT_TAX_REASON,
    POLICY_VERSION,
    BENCHMARK_SNAPSHOTS,
    DomainError,
    compute_price_benchmark,
    compute_price_simulation,
    ensure_idr_bound,
    round_idr,
    validate_benchmark_input,
    validate_offering_input,
    validate_purchase_input,
    validate_sale_input,
    validate_simulation_input,
    validate_workspace_input,
)

JAKARTA_TZ = ZoneInfo("Asia/Jakarta")
DEMO_SCENARIO_SLUG = "warung_bakso_sembako_v1"

# Local synthetic principals for baseline development/testing (never real credentials)
SYNTHETIC_PRINCIPALS: dict[str, str] = {
    "synthetic_owner": "dev-owner-pass",
    "actor_a": "dev-a-pass",
    "actor_b": "dev-b-pass",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_occurred_at(raw: Any, provided: bool = False) -> str:
    if not provided and raw is None:
        return _utc_now()
    if not isinstance(raw, str) or not raw.strip():
        raise DomainError(422, "invalid_timestamp", "occurred_at harus berupa string ISO-8601 dengan timezone.")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DomainError(422, "invalid_timestamp", f"Format occurred_at tidak valid: {exc}") from exc
    if dt.tzinfo is None:
        raise DomainError(422, "invalid_timestamp", "occurred_at wajib menyertakan timezone/offset (tidak boleh naive).")
    return dt.astimezone(timezone.utc).isoformat()


def _hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _record_audit(
    conn: Any,
    workspace_id: str,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO audit_events (
            event_id, workspace_id, actor, action, entity_type, entity_id, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"evt_{uuid.uuid4().hex[:12]}",
            workspace_id,
            actor,
            action,
            entity_type,
            entity_id,
            json.dumps(payload, sort_keys=True),
            _utc_now(),
        ),
    )


def _row_to_offering(row: Any) -> dict[str, Any]:
    req_stock = bool(row["requires_stock_movement"])
    keys = row.keys()
    if req_stock:
        raw_qty = row["pool_qty_on_hand"] if "pool_qty_on_hand" in keys else None
        raw_val = row["pool_total_value_idr"] if "pool_total_value_idr" in keys else None
        qty_dec = Decimal(raw_qty) if raw_qty is not None else Decimal("0")
        val_idr = int(raw_val) if raw_val is not None else 0
        qty_on_hand: str | None = format(qty_dec.normalize(), "f") if qty_dec != 0 else "0"
        inventory_value_idr: int | None = val_idr
        wa_unit_cost_idr: int | None = (
            round_idr(Decimal(val_idr) / qty_dec) if qty_dec > 0 else None
        )
    else:
        qty_on_hand = None
        inventory_value_idr = None
        wa_unit_cost_idr = None
    return {
        "offering_id": row["offering_id"],
        "workspace_id": row["workspace_id"],
        "name": row["name"],
        "offering_type": row["offering_type"],
        "unit_price_idr": row["unit_price_idr"],
        "currency": "IDR",
        "unit": row["unit"],
        "requires_stock_movement": req_stock,
        "valuation_method": row["valuation_method"],
        "qty_on_hand": qty_on_hand,
        "inventory_value_idr": inventory_value_idr,
        "wa_unit_cost_idr": wa_unit_cost_idr,
        "tax_status": row["tax_status"],
        "tax_reason": row["tax_reason"],
        "created_at": row["created_at"],
    }


def _row_to_workspace(row: Any) -> dict[str, Any]:
    keys = row.keys()
    return {
        "workspace_id": row["workspace_id"],
        "name": row["name"],
        "business_type": row["business_type"],
        "currency": row["currency"],
        "timezone": row["timezone"],
        "is_demo": bool(row["is_demo"]) if "is_demo" in keys else False,
        "demo_slug": row["demo_slug"] if "demo_slug" in keys else None,
        "created_at": row["created_at"],
    }


class BaselineService:
    """Modular monolith service for Workspaces, Offerings, Purchases, Sales, and Reports."""

    def __init__(
        self,
        db_path: str | DatabaseConfig | None = None,
        *,
        database_url: str | None = None,
        backend: str | None = None,
        pool: PostgresPoolManager | None = None,
        creative_assets_dir: str | Path | None = None,
    ) -> None:
        self.db_config = resolve_db_config(db_path=db_path, database_url=database_url, backend=backend)
        self.backend = self.db_config.backend
        self.db_path = self.db_config.target if self.backend == "sqlite" else self.db_config.display_target
        self._pool = pool
        self._owns_pool = False
        self.creative_assets_dir = Path(creative_assets_dir) if creative_assets_dir is not None else DEFAULT_ASSETS_DIR

    def close(self) -> None:
        """Close owned database pool resources cleanly."""
        if self._owns_pool and self._pool is not None:
            self._pool.close()
            self._owns_pool = False

    def _tx(self, immediate: bool = False):
        return db_transaction(self.db_config, immediate=immediate, pool=self._pool)

    def create_session(self, actor_id: str, passcode: str = "") -> dict[str, Any]:
        clean_actor = actor_id.strip() if isinstance(actor_id, str) else ""
        expected = SYNTHETIC_PRINCIPALS.get(clean_actor)
        if not expected or not isinstance(passcode, str) or not hmac.compare_digest(passcode, expected):
            raise DomainError(401, "unauthenticated", "Kredensial principal tidak valid.")
        token = f"sess_{uuid.uuid4().hex}"
        created_at = _utc_now()
        with self._tx(immediate=True) as conn:
            conn.execute(
                "INSERT INTO sessions (token, actor_id, created_at, revoked_at) VALUES (?, ?, ?, NULL)",
                (token, clean_actor, created_at),
            )
        return {"token": token, "actor_id": clean_actor, "created_at": created_at}

    def resolve_session(self, token: str | None) -> str:
        if not token:
            raise DomainError(401, "unauthenticated", "Session token wajib disertakan.")
        with self._tx() as conn:
            row = conn.execute(
                "SELECT actor_id, revoked_at FROM sessions WHERE token = ?",
                (token,),
            ).fetchone()
            if not row or row["revoked_at"] is not None:
                raise DomainError(401, "unauthenticated", "Session tidak valid atau telah dicabut.")
            return str(row["actor_id"])

    def revoke_membership(self, workspace_id: str, actor_id: str) -> None:
        with self._tx(immediate=True) as conn:
            conn.acquire_write_lock(f"workspace:{workspace_id}")
            conn.execute(
                "UPDATE workspace_memberships SET revoked_at = ? WHERE workspace_id = ? AND actor_id = ?",
                (_utc_now(), workspace_id, actor_id),
            )

    def list_workspaces(self, actor_id: str) -> list[dict[str, Any]]:
        with self._tx() as conn:
            rows = conn.execute(
                """
                SELECT w.* FROM workspaces w
                JOIN workspace_memberships m ON m.workspace_id = w.workspace_id
                WHERE m.actor_id = ? AND m.revoked_at IS NULL
                ORDER BY w.created_at ASC
                """,
                (actor_id,),
            ).fetchall()
            return [_row_to_workspace(r) for r in rows]

    def create_workspace(
        self,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        actor: str = "synthetic_owner",
    ) -> tuple[int, dict[str, Any]]:
        validated = validate_workspace_input(payload)
        req_hash = _hash_payload(payload)

        with self._tx(immediate=True) as conn:
            conn.acquire_write_lock(f"principal:{actor}")
            if idempotency_key:
                existing = conn.execute(
                    """
                    SELECT request_hash, status_code, response_body
                    FROM idempotency_keys
                    WHERE workspace_id = ? AND operation = ? AND idempotency_key = ?
                    """,
                    (f"principal:{actor}", "create_workspace", idempotency_key),
                ).fetchone()
                if existing:
                    replayed = json.loads(existing["response_body"])
                    ws_id = replayed["workspace_id"]
                    mem = conn.execute(
                        "SELECT revoked_at FROM workspace_memberships WHERE workspace_id = ? AND actor_id = ?",
                        (ws_id, actor),
                    ).fetchone()
                    if not mem or mem["revoked_at"] is not None:
                        raise DomainError(403, "forbidden_workspace", "Keanggotaan workspace telah dicabut.")
                    if existing["request_hash"] != req_hash:
                        raise DomainError(
                            409,
                            "idempotency_conflict",
                            "Idempotency-Key sudah dipakai dengan payload berbeda.",
                        )
                    return existing["status_code"], replayed

            workspace_id = f"ws_{uuid.uuid4().hex[:12]}"
            created_at = _utc_now()
            conn.execute(
                """
                INSERT INTO workspaces (workspace_id, name, business_type, currency, timezone, created_at)
                VALUES (?, ?, ?, 'IDR', ?, ?)
                """,
                (workspace_id, validated.name, validated.business_type, validated.timezone, created_at),
            )
            conn.execute(
                """
                INSERT INTO workspace_memberships (workspace_id, actor_id, role, created_at, revoked_at)
                VALUES (?, ?, 'owner', ?, NULL)
                """,
                (workspace_id, actor, created_at),
            )
            result = {
                "workspace_id": workspace_id,
                "name": validated.name,
                "business_type": validated.business_type,
                "currency": "IDR",
                "timezone": validated.timezone,
                "is_demo": False,
                "demo_slug": None,
                "created_at": created_at,
            }
            _record_audit(conn, workspace_id, actor, "workspace.created", "workspace", workspace_id, result)

            if idempotency_key:
                conn.execute(
                    """
                    INSERT INTO idempotency_keys (
                        workspace_id, operation, idempotency_key, request_hash, status_code, response_body, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (f"principal:{actor}", "create_workspace", idempotency_key, req_hash, 201, json.dumps(result), created_at),
                )
            return 201, result

    def _assert_workspace_access(
        self,
        conn: Any,
        workspace_id: str,
        actor_id: str | None,
    ) -> None:
        if not actor_id:
            raise DomainError(401, "unauthenticated", "Aktor tidak terautentikasi.")
        ws = conn.execute(
            "SELECT workspace_id FROM workspaces WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        membership = conn.execute(
            """
            SELECT role, revoked_at FROM workspace_memberships
            WHERE workspace_id = ? AND actor_id = ?
            """,
            (workspace_id, actor_id),
        ).fetchone()
        if not ws or not membership or membership["revoked_at"] is not None:
            raise DomainError(
                404,
                "workspace_not_found",
                "Workspace tidak ditemukan atau akses ditolak.",
            )

    def require_poster_access(self, workspace_id: str, actor_id: str) -> None:
        """Authorize poster requests before decoding their body."""
        with self._tx() as conn:
            self._assert_poster_access(conn, workspace_id, actor_id)

    def _check_idempotency(
        self,
        conn: Any,
        workspace_id: str,
        operation: str,
        idempotency_key: str | None,
        req_hash: str,
    ) -> tuple[int, dict[str, Any]] | None:
        if not idempotency_key:
            return None
        existing = conn.execute(
            """
            SELECT request_hash, status_code, response_body
            FROM idempotency_keys
            WHERE workspace_id = ? AND operation = ? AND idempotency_key = ?
            """,
            (workspace_id, operation, idempotency_key),
        ).fetchone()
        if not existing:
            return None
        if existing["request_hash"] != req_hash:
            raise DomainError(
                409,
                "idempotency_conflict",
                "Idempotency-Key sudah dipakai dengan payload berbeda.",
            )
        return existing["status_code"], json.loads(existing["response_body"])

    def _save_idempotency(
        self,
        conn: Any,
        workspace_id: str,
        operation: str,
        idempotency_key: str | None,
        req_hash: str,
        status_code: int,
        result: dict[str, Any],
        created_at: str,
    ) -> None:
        if not idempotency_key:
            return
        conn.execute(
            """
            INSERT INTO idempotency_keys (
                workspace_id, operation, idempotency_key, request_hash, status_code, response_body, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (workspace_id, operation, idempotency_key, req_hash, status_code, json.dumps(result), created_at),
        )

    def list_offerings(
        self,
        workspace_id: str,
        actor_id: str | None,
        actor_status: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._tx() as conn:
            self._assert_workspace_access(conn, workspace_id, actor_id)
            rows = conn.execute(
                """
                SELECT o.*, p.qty_on_hand AS pool_qty_on_hand, p.total_value_idr AS pool_total_value_idr
                FROM offerings o
                LEFT JOIN inventory_pools p
                    ON p.workspace_id = o.workspace_id AND p.offering_id = o.offering_id
                WHERE o.workspace_id = ?
                ORDER BY o.created_at ASC
                """,
                (workspace_id,),
            ).fetchall()
            return [_row_to_offering(r) for r in rows]

    def get_offering(
        self,
        workspace_id: str,
        offering_id: str,
        actor_id: str | None,
        actor_status: str | None = None,
    ) -> dict[str, Any]:
        with self._tx() as conn:
            self._assert_workspace_access(conn, workspace_id, actor_id)
            row = conn.execute(
                """
                SELECT o.*, p.qty_on_hand AS pool_qty_on_hand, p.total_value_idr AS pool_total_value_idr
                FROM offerings o
                LEFT JOIN inventory_pools p
                    ON p.workspace_id = o.workspace_id AND p.offering_id = o.offering_id
                WHERE o.workspace_id = ? AND o.offering_id = ?
                """,
                (workspace_id, offering_id),
            ).fetchone()
            if not row:
                raise DomainError(404, "offering_not_found", "Offering tidak ditemukan pada workspace ini.")
            return _row_to_offering(row)

    def create_offering(
        self,
        workspace_id: str,
        actor_id: str | None,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        actor: str = "synthetic_owner",
        actor_status: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        with self._tx(immediate=True) as conn:
            conn.acquire_write_lock(f"workspace:{workspace_id}")
            self._assert_workspace_access(conn, workspace_id, actor_id)
            validated = validate_offering_input(payload)
            req_hash = _hash_payload(payload)

            replay = self._check_idempotency(conn, workspace_id, "create_offering", idempotency_key, req_hash)
            if replay:
                return replay

            offering_id = f"off_{uuid.uuid4().hex[:12]}"
            created_at = _utc_now()
            conn.execute(
                """
                INSERT INTO offerings (
                    offering_id, workspace_id, name, offering_type, unit_price_idr,
                    unit, requires_stock_movement, valuation_method,
                    tax_status, tax_reason, tax_amount, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    offering_id,
                    workspace_id,
                    validated.name,
                    validated.offering_type,
                    validated.unit_price_idr,
                    validated.unit,
                    bool(validated.requires_stock_movement),
                    validated.valuation_method,
                    validated.tax_status,
                    validated.tax_reason,
                    created_at,
                ),
            )
            result = {
                "offering_id": offering_id,
                "workspace_id": workspace_id,
                "name": validated.name,
                "offering_type": validated.offering_type,
                "unit_price_idr": validated.unit_price_idr,
                "currency": "IDR",
                "unit": validated.unit,
                "requires_stock_movement": bool(validated.requires_stock_movement),
                "valuation_method": validated.valuation_method,
                "qty_on_hand": "0" if validated.requires_stock_movement else None,
                "inventory_value_idr": 0 if validated.requires_stock_movement else None,
                "wa_unit_cost_idr": None,
                "tax_status": validated.tax_status,
                "tax_reason": validated.tax_reason,
                "created_at": created_at,
            }
            _record_audit(conn, workspace_id, actor, "offering.created", "offering", offering_id, result)
            self._save_idempotency(
                conn, workspace_id, "create_offering", idempotency_key, req_hash, 201, result, created_at
            )
            return 201, result

    def create_purchase(
        self,
        workspace_id: str,
        actor_id: str | None,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        actor: str = "synthetic_owner",
        actor_status: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        with self._tx(immediate=True) as conn:
            conn.acquire_write_lock(f"workspace:{workspace_id}")
            self._assert_workspace_access(conn, workspace_id, actor_id)
            validated = validate_purchase_input(payload)
            req_hash = _hash_payload(payload)

            replay = self._check_idempotency(conn, workspace_id, "create_purchase", idempotency_key, req_hash)
            if replay:
                return replay

            off = conn.execute(
                "SELECT * FROM offerings WHERE workspace_id = ? AND offering_id = ?",
                (workspace_id, validated.offering_id),
            ).fetchone()
            if not off:
                raise DomainError(404, "offering_not_found", "Offering tidak ditemukan pada workspace ini.")
            if not off["requires_stock_movement"]:
                raise DomainError(
                    422,
                    "service_no_stock",
                    "Offering jasa tidak memerlukan pembelian/pergerakan stok.",
                )

            occurred_at = _normalize_occurred_at(
                payload.get("occurred_at"), provided=("occurred_at" in payload)
            )
            max_mov = conn.execute(
                "SELECT MAX(occurred_at) AS max_ts FROM stock_movements WHERE workspace_id = ? AND offering_id = ?",
                (workspace_id, validated.offering_id),
            ).fetchone()
            if (
                max_mov
                and max_mov["max_ts"]
                and datetime.fromisoformat(occurred_at) < datetime.fromisoformat(max_mov["max_ts"])
            ):
                raise DomainError(
                    422,
                    "out_of_order_timestamp",
                    "occurred_at tidak boleh lebih awal dari mutasi stok terakhir.",
                )
            recorded_at = _utc_now()
            purchase_id = f"pur_{uuid.uuid4().hex[:12]}"
            batch_id = f"bat_{uuid.uuid4().hex[:12]}"
            movement_id = f"mov_{uuid.uuid4().hex[:12]}"
            cash_id = f"csh_{uuid.uuid4().hex[:12]}"
            qty_str = str(validated.qty)
            unit_cost_dec = Decimal(validated.total_cost_idr) / validated.qty

            conn.execute(
                """
                INSERT INTO purchases (
                    purchase_id, workspace_id, offering_id, qty, total_cost_idr,
                    payment_method, occurred_at, recorded_at
                ) VALUES (?, ?, ?, ?, ?, 'cash', ?, ?)
                """,
                (purchase_id, workspace_id, validated.offering_id, qty_str, validated.total_cost_idr, occurred_at, recorded_at),
            )
            conn.execute(
                """
                INSERT INTO inventory_batches (
                    batch_id, workspace_id, offering_id, purchase_id, qty_initial, qty_remaining,
                    total_cost_idr, occurred_at, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (batch_id, workspace_id, validated.offering_id, purchase_id, qty_str, qty_str, validated.total_cost_idr, occurred_at, recorded_at),
            )
            conn.execute(
                """
                INSERT INTO stock_movements (
                    movement_id, workspace_id, offering_id, movement_type, qty_delta,
                    unit_cost_idr, total_cost_idr, reference_type, reference_id, occurred_at, recorded_at
                ) VALUES (?, ?, ?, 'purchase_in', ?, ?, ?, 'purchase', ?, ?, ?)
                """,
                (movement_id, workspace_id, validated.offering_id, qty_str, str(unit_cost_dec), validated.total_cost_idr, purchase_id, occurred_at, recorded_at),
            )
            conn.execute(
                """
                INSERT INTO cash_movements (
                    cash_id, workspace_id, direction, amount_idr, reference_type, reference_id, occurred_at, recorded_at
                ) VALUES (?, ?, 'out', ?, 'purchase', ?, ?, ?)
                """,
                (cash_id, workspace_id, validated.total_cost_idr, purchase_id, occurred_at, recorded_at),
            )
            pool = conn.execute(
                "SELECT qty_on_hand, total_value_idr FROM inventory_pools WHERE workspace_id = ? AND offering_id = ?",
                (workspace_id, validated.offering_id),
            ).fetchone()
            if pool:
                new_qty = Decimal(pool["qty_on_hand"]) + validated.qty
                new_val = int(pool["total_value_idr"]) + validated.total_cost_idr
                ensure_idr_bound(new_val, "total_value_idr")
                conn.execute(
                    "UPDATE inventory_pools SET qty_on_hand = ?, total_value_idr = ? WHERE workspace_id = ? AND offering_id = ?",
                    (str(new_qty), new_val, workspace_id, validated.offering_id),
                )
            else:
                conn.execute(
                    "INSERT INTO inventory_pools (workspace_id, offering_id, qty_on_hand, total_value_idr) VALUES (?, ?, ?, ?)",
                    (workspace_id, validated.offering_id, qty_str, validated.total_cost_idr),
                )

            result = {
                "purchase_id": purchase_id,
                "workspace_id": workspace_id,
                "offering_id": validated.offering_id,
                "batch_id": batch_id,
                "qty": qty_str,
                "total_cost_idr": validated.total_cost_idr,
                "currency": "IDR",
                "occurred_at": occurred_at,
                "recorded_at": recorded_at,
            }
            _record_audit(conn, workspace_id, actor, "purchase.created", "purchase", purchase_id, result)
            self._save_idempotency(
                conn, workspace_id, "create_purchase", idempotency_key, req_hash, 201, result, recorded_at
            )
            return 201, result

    def create_sale(
        self,
        workspace_id: str,
        actor_id: str | None,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        actor: str = "synthetic_owner",
        actor_status: str | None = None,
        fault_injector: Callable[[Any], None] | None = None,
        fault_stage: str = "pre_commit",
    ) -> tuple[int, dict[str, Any]]:
        with self._tx(immediate=True) as conn:
            conn.acquire_write_lock(f"workspace:{workspace_id}")
            self._assert_workspace_access(conn, workspace_id, actor_id)
            validated = validate_sale_input(payload)
            req_hash = _hash_payload(payload)

            replay = self._check_idempotency(conn, workspace_id, "create_sale", idempotency_key, req_hash)
            if replay:
                return replay

            occurred_at = _normalize_occurred_at(
                payload.get("occurred_at"), provided=("occurred_at" in payload)
            )
            recorded_at = _utc_now()
            sale_id = f"sal_{uuid.uuid4().hex[:12]}"

            total_revenue_idr = 0
            total_cogs_idr: int | None = 0
            sale_cogs_status = "assessed"
            line_results: list[dict[str, Any]] = []

            for line in validated.lines:
                off = conn.execute(
                    "SELECT * FROM offerings WHERE workspace_id = ? AND offering_id = ?",
                    (workspace_id, line.offering_id),
                ).fetchone()
                if not off:
                    raise DomainError(404, "offering_not_found", f"Offering {line.offering_id} tidak ditemukan.")

                revenue_idr = (
                    line.total_price_idr
                    if line.total_price_idr is not None
                    else round_idr(line.qty * Decimal(off["unit_price_idr"]))
                )
                ensure_idr_bound(revenue_idr, "revenue_idr")
                total_revenue_idr += revenue_idr
                ensure_idr_bound(total_revenue_idr, "total_revenue_idr")

                line_cogs_idr: int | None = None
                line_cost_status = "open"

                if off["requires_stock_movement"]:
                    max_mov = conn.execute(
                        "SELECT MAX(occurred_at) AS max_ts FROM stock_movements WHERE workspace_id = ? AND offering_id = ?",
                        (workspace_id, line.offering_id),
                    ).fetchone()
                    if (
                        max_mov
                        and max_mov["max_ts"]
                        and datetime.fromisoformat(occurred_at) < datetime.fromisoformat(max_mov["max_ts"])
                    ):
                        raise DomainError(
                            422,
                            "out_of_order_timestamp",
                            "occurred_at tidak boleh lebih awal dari mutasi stok terakhir.",
                        )

                    pool = conn.execute(
                        "SELECT qty_on_hand, total_value_idr FROM inventory_pools WHERE workspace_id = ? AND offering_id = ?",
                        (workspace_id, line.offering_id),
                    ).fetchone()
                    qty_on_hand = Decimal(pool["qty_on_hand"]) if pool else Decimal("0")
                    total_val_idr = int(pool["total_value_idr"]) if pool else 0

                    if qty_on_hand < line.qty:
                        raise DomainError(
                            409,
                            "insufficient_stock",
                            f"Stok tidak mencukupi untuk {off['name']} (tersedia {qty_on_hand}, diminta {line.qty}).",
                        )

                    if line.qty == qty_on_hand:
                        line_cogs_idr = total_val_idr
                        new_qty = Decimal("0")
                        new_val_idr = 0
                        wa_unit_cost = Decimal(total_val_idr) / qty_on_hand
                    else:
                        wa_unit_cost = Decimal(total_val_idr) / qty_on_hand
                        line_cogs_idr = round_idr(line.qty * wa_unit_cost)
                        new_qty = qty_on_hand - line.qty
                        new_val_idr = total_val_idr - line_cogs_idr

                    line_cost_status = "assessed"
                    if total_cogs_idr is not None:
                        total_cogs_idr += line_cogs_idr

                    conn.execute(
                        "UPDATE inventory_pools SET qty_on_hand = ?, total_value_idr = ? WHERE workspace_id = ? AND offering_id = ?",
                        (str(new_qty), new_val_idr, workspace_id, line.offering_id),
                    )

                    # Keep inventory_batches.qty_remaining synchronized with inventory_pools
                    batches = conn.execute(
                        """
                        SELECT batch_id, qty_remaining
                        FROM inventory_batches
                        WHERE workspace_id = ? AND offering_id = ? AND CAST(qty_remaining AS NUMERIC) > 0
                        ORDER BY occurred_at ASC, batch_id ASC
                        """,
                        (workspace_id, line.offering_id),
                    ).fetchall()
                    rem_deduct = line.qty
                    for b in batches:
                        if rem_deduct <= 0:
                            break
                        b_rem = Decimal(b["qty_remaining"])
                        take = min(b_rem, rem_deduct)
                        conn.execute(
                            "UPDATE inventory_batches SET qty_remaining = ? WHERE batch_id = ?",
                            (str(b_rem - take), b["batch_id"]),
                        )
                        rem_deduct -= take

                    if fault_injector is not None and fault_stage == "stock_movements":
                        fault_injector(conn)

                    conn.execute(
                        """
                        INSERT INTO stock_movements (
                            movement_id, workspace_id, offering_id, movement_type, qty_delta,
                            unit_cost_idr, total_cost_idr, reference_type, reference_id, occurred_at, recorded_at
                        ) VALUES (?, ?, ?, 'sale_out', ?, ?, ?, 'sale', ?, ?, ?)
                        """,
                        (
                            f"mov_{uuid.uuid4().hex[:12]}",
                            workspace_id,
                            line.offering_id,
                            str(-line.qty),
                            str(wa_unit_cost),
                            line_cogs_idr,
                            sale_id,
                            occurred_at,
                            recorded_at,
                        ),
                    )
                else:
                    # Service / uncosted line: no stock movement, cost explicitly open
                    sale_cogs_status = "open"
                    total_cogs_idr = None

                line_id = f"lin_{uuid.uuid4().hex[:12]}"
                line_results.append(
                    {
                        "line_id": line_id,
                        "offering_id": line.offering_id,
                        "offering_type": off["offering_type"],
                        "qty": str(line.qty),
                        "revenue_idr": revenue_idr,
                        "cogs_idr": line_cogs_idr,
                        "cost_status": line_cost_status,
                    }
                )

            if total_cogs_idr is not None:
                ensure_idr_bound(total_cogs_idr, "total_cogs_idr")

            conn.execute(
                """
                INSERT INTO sales (
                    sale_id, workspace_id, total_revenue_idr, total_cogs_idr, cogs_status,
                    policy_version, tax_status, tax_reason, occurred_at, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'not_assessed', ?, ?, ?)
                """,
                (
                    sale_id,
                    workspace_id,
                    total_revenue_idr,
                    total_cogs_idr,
                    sale_cogs_status,
                    POLICY_VERSION,
                    DEFAULT_TAX_REASON,
                    occurred_at,
                    recorded_at,
                ),
            )
            for lr in line_results:
                conn.execute(
                    """
                    INSERT INTO sale_lines (
                        line_id, sale_id, workspace_id, offering_id, offering_type,
                        qty, revenue_idr, cogs_idr, cost_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lr["line_id"],
                        sale_id,
                        workspace_id,
                        lr["offering_id"],
                        lr["offering_type"],
                        lr["qty"],
                        lr["revenue_idr"],
                        lr["cogs_idr"],
                        lr["cost_status"],
                    ),
                )

            conn.execute(
                """
                INSERT INTO cash_movements (
                    cash_id, workspace_id, direction, amount_idr, reference_type, reference_id, occurred_at, recorded_at
                ) VALUES (?, ?, 'in', ?, 'sale', ?, ?, ?)
                """,
                (f"csh_{uuid.uuid4().hex[:12]}", workspace_id, total_revenue_idr, sale_id, occurred_at, recorded_at),
            )

            gross_profit_idr = (
                total_revenue_idr - total_cogs_idr if total_cogs_idr is not None else None
            )
            result = {
                "sale_id": sale_id,
                "workspace_id": workspace_id,
                "total_revenue_idr": total_revenue_idr,
                "total_cogs_idr": total_cogs_idr,
                "cogs_status": sale_cogs_status,
                "gross_profit_idr": gross_profit_idr,
                "policy_version": POLICY_VERSION,
                "tax_status": "not_assessed",
                "tax_reason": DEFAULT_TAX_REASON,
                "currency": "IDR",
                "lines": line_results,
                "occurred_at": occurred_at,
                "recorded_at": recorded_at,
            }
            _record_audit(conn, workspace_id, actor, "sale.created", "sale", sale_id, result)
            self._save_idempotency(
                conn, workspace_id, "create_sale", idempotency_key, req_hash, 201, result, recorded_at
            )

            if fault_injector is not None and fault_stage == "pre_commit":
                fault_injector(conn)

            return 201, result

    def get_daily_report(
        self,
        workspace_id: str,
        actor_id: str | None,
        date_str: str | None = None,
        actor_status: str | None = None,
    ) -> dict[str, Any]:
        with self._tx() as conn:
            self._assert_workspace_access(conn, workspace_id, actor_id)

            ws_row = conn.execute(
                "SELECT timezone FROM workspaces WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
            ws_tz_name = ws_row["timezone"] if ws_row else "Asia/Jakarta"
            ws_tz = ZoneInfo(ws_tz_name)

            if date_str:
                try:
                    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError as exc:
                    raise DomainError(422, "invalid_date", "Format tanggal harus YYYY-MM-DD.") from exc
            else:
                target_date = datetime.now(ws_tz).date()

            start_local = datetime(target_date.year, target_date.month, target_date.day, tzinfo=ws_tz)
            end_local = start_local + timedelta(days=1)
            start_utc = start_local.astimezone(timezone.utc).isoformat()
            end_utc = end_local.astimezone(timezone.utc).isoformat()

            sales_rows = conn.execute(
                """
                SELECT * FROM sales
                WHERE workspace_id = ? AND occurred_at >= ? AND occurred_at < ?
                ORDER BY occurred_at ASC
                """,
                (workspace_id, start_utc, end_utc),
            ).fetchall()

            revenue_idr = sum(r["total_revenue_idr"] for r in sales_rows)
            has_open_cogs = any(r["cogs_status"] == "open" for r in sales_rows)
            if has_open_cogs:
                cogs_idr: int | None = None
                cogs_status = "open"
                gross_profit_idr: int | None = None
                gross_profit_status = "unavailable"
            else:
                cogs_idr = sum((r["total_cogs_idr"] or 0) for r in sales_rows)
                cogs_status = "assessed"
                gross_profit_idr = revenue_idr - cogs_idr
                gross_profit_status = "assessed"

            cash_rows = conn.execute(
                """
                SELECT * FROM cash_movements
                WHERE workspace_id = ? AND occurred_at >= ? AND occurred_at < ?
                ORDER BY occurred_at ASC
                """,
                (workspace_id, start_utc, end_utc),
            ).fetchall()
            cash_in_idr = sum(r["amount_idr"] for r in cash_rows if r["direction"] == "in")
            cash_out_idr = sum(r["amount_idr"] for r in cash_rows if r["direction"] == "out")
            net_cash_flow_idr = cash_in_idr - cash_out_idr

            # Ending inventory snapshot reconstructed strictly from stock_movements < end_utc
            mov_rows = conn.execute(
                """
                SELECT m.offering_id, o.name, o.unit, m.movement_type, m.qty_delta, m.total_cost_idr
                FROM stock_movements m
                JOIN offerings o ON o.offering_id = m.offering_id
                WHERE m.workspace_id = ? AND m.occurred_at < ?
                """,
                (workspace_id, end_utc),
            ).fetchall()

            inv_by_off: dict[str, dict[str, Any]] = {}
            for m in mov_rows:
                oid = m["offering_id"]
                if oid not in inv_by_off:
                    inv_by_off[oid] = {
                        "offering_id": oid,
                        "name": m["name"],
                        "unit": m["unit"],
                        "qty": Decimal("0"),
                        "value_idr": 0,
                    }
                inv_by_off[oid]["qty"] += Decimal(m["qty_delta"])
                cost = int(m["total_cost_idr"] or 0)
                if m["movement_type"] == "purchase_in":
                    inv_by_off[oid]["value_idr"] += cost
                else:
                    inv_by_off[oid]["value_idr"] -= cost

            inv_items = []
            total_inv_qty = Decimal("0")
            total_inv_value_idr = 0
            for oid, item in inv_by_off.items():
                val_idr = item["value_idr"]
                total_inv_qty += item["qty"]
                total_inv_value_idr += val_idr
                inv_items.append(
                    {
                        "offering_id": item["offering_id"],
                        "name": item["name"],
                        "unit": item["unit"],
                        "qty_remaining": str(item["qty"]),
                        "value_idr": val_idr,
                    }
                )

            purchase_rows = conn.execute(
                """
                SELECT p.*, o.name AS offering_name, o.unit AS unit
                FROM purchases p
                LEFT JOIN offerings o ON o.offering_id = p.offering_id
                WHERE p.workspace_id = ? AND p.occurred_at >= ? AND p.occurred_at < ?
                ORDER BY p.occurred_at ASC
                """,
                (workspace_id, start_utc, end_utc),
            ).fetchall()
            sale_ids = [r["sale_id"] for r in sales_rows]
            lines_by_sale: dict[str, list[dict[str, Any]]] = {}
            if sale_ids:
                placeholders = ",".join("?" for _ in sale_ids)
                line_rows = conn.execute(
                    f"""
                    SELECT l.*, o.name AS offering_name, o.unit AS unit
                    FROM sale_lines l
                    LEFT JOIN offerings o ON o.offering_id = l.offering_id
                    WHERE l.workspace_id = ? AND l.sale_id IN ({placeholders})
                    ORDER BY l.line_id ASC
                    """,
                    (workspace_id, *sale_ids),
                ).fetchall()
                for lr in line_rows:
                    lines_by_sale.setdefault(lr["sale_id"], []).append(dict(lr))
            sales_drill: list[dict[str, Any]] = []
            for r in sales_rows:
                sale_item = dict(r)
                sale_item["lines"] = lines_by_sale.get(r["sale_id"], [])
                sales_drill.append(sale_item)
            movement_rows = conn.execute(
                """
                SELECT m.*, o.name AS offering_name, o.unit AS unit
                FROM stock_movements m
                LEFT JOIN offerings o ON o.offering_id = m.offering_id
                WHERE m.workspace_id = ? AND m.occurred_at >= ? AND m.occurred_at < ?
                ORDER BY m.occurred_at ASC
                """,
                (workspace_id, start_utc, end_utc),
            ).fetchall()
            audit_rows = conn.execute(
                """
                SELECT * FROM audit_events
                WHERE workspace_id = ? AND created_at >= ? AND created_at < ?
                ORDER BY created_at DESC LIMIT 50
                """,
                (workspace_id, start_utc, end_utc),
            ).fetchall()

            return {
                "workspace_id": workspace_id,
                "period": {
                    "date": target_date.isoformat(),
                    "timezone": ws_tz_name,
                    "start_utc": start_utc,
                    "end_utc": end_utc,
                },
                "policy_version": POLICY_VERSION,
                "tax_status": "not_assessed",
                "tax_reason": DEFAULT_TAX_REASON,
                "currency": "IDR",
                "revenue_idr": revenue_idr,
                "cogs_idr": cogs_idr,
                "cogs_status": cogs_status,
                "gross_profit_idr": gross_profit_idr,
                "gross_profit_status": gross_profit_status,
                "cash_in_idr": cash_in_idr,
                "cash_out_idr": cash_out_idr,
                "net_cash_flow_idr": net_cash_flow_idr,
                "ending_inventory": {
                    "total_qty": str(total_inv_qty),
                    "total_value_idr": total_inv_value_idr,
                    "items": inv_items,
                },
                "drill_down": {
                    "purchases": [dict(r) for r in purchase_rows],
                    "sales": sales_drill,
                    "stock_movements": [dict(r) for r in movement_rows],
                    "cash_movements": [dict(r) for r in cash_rows],
                    "audit_events": [dict(r) for r in audit_rows],
                },
            }

    def bootstrap_demo_workspace(
        self,
        actor_id: str,
        scenario_slug: str = DEMO_SCENARIO_SLUG,
    ) -> tuple[int, dict[str, Any]]:
        """Idempotently provision an isolated synthetic demo workspace with exact oracle fixtures."""
        if not actor_id:
            raise DomainError(401, "unauthenticated", "Aktor tidak terautentikasi.")
        if scenario_slug != DEMO_SCENARIO_SLUG:
            raise DomainError(
                422,
                "invalid_demo_scenario",
                "Skenario demo tidak dikenal.",
                {"scenario_slug": f"Gunakan '{DEMO_SCENARIO_SLUG}'."},
            )

        now_jkt = datetime.now(JAKARTA_TZ)
        demo_date = now_jkt.date().isoformat()
        start_of_day = datetime(now_jkt.year, now_jkt.month, now_jkt.day, tzinfo=JAKARTA_TZ)
        if (now_jkt - start_of_day).total_seconds() >= 180:
            t1_dt = now_jkt - timedelta(seconds=120)
            t2_dt = now_jkt - timedelta(seconds=60)
            t3_dt = now_jkt - timedelta(seconds=10)
        else:
            t1_dt = start_of_day
            t2_dt = start_of_day
            t3_dt = start_of_day
        t1 = t1_dt.astimezone(timezone.utc).isoformat()
        t2 = t2_dt.astimezone(timezone.utc).isoformat()
        t3 = t3_dt.astimezone(timezone.utc).isoformat()

        with self._tx(immediate=True) as conn:
            conn.acquire_write_lock(f"principal:{actor_id}")
            existing = conn.execute(
                """
                SELECT w.* FROM workspaces w
                JOIN workspace_memberships m ON m.workspace_id = w.workspace_id
                WHERE m.actor_id = ? AND m.revoked_at IS NULL
                    AND w.is_demo = ? AND w.demo_slug = ?
                ORDER BY w.created_at ASC LIMIT 1
                """,
                (actor_id, True, scenario_slug),
            ).fetchone()
            if existing:
                seed_row = conn.execute(
                    "SELECT MIN(occurred_at) AS first_ts FROM purchases WHERE workspace_id = ?",
                    (existing["workspace_id"],),
                ).fetchone()
                seed_ts = (
                    seed_row["first_ts"]
                    if seed_row and seed_row["first_ts"]
                    else existing["created_at"]
                )
                seed_dt = datetime.fromisoformat(str(seed_ts).replace("Z", "+00:00"))
                if seed_dt.tzinfo is None:
                    seed_dt = seed_dt.replace(tzinfo=timezone.utc)
                existing_demo_date = seed_dt.astimezone(JAKARTA_TZ).date().isoformat()
                return 200, {
                    "workspace": _row_to_workspace(existing),
                    "created": False,
                    "idempotent_replay": True,
                    "scenario_slug": scenario_slug,
                    "demo_date": existing_demo_date,
                }

            now_utc = _utc_now()
            ws_id = f"ws_{uuid.uuid4().hex[:12]}"
            ws_name = "Warung Bakso & Sembako (Demo Sintetis)"
            conn.execute(
                """
                INSERT INTO workspaces (
                    workspace_id, name, business_type, currency, timezone, is_demo, demo_slug, created_at
                ) VALUES (?, ?, 'umkm_hybrid', 'IDR', 'Asia/Jakarta', ?, ?, ?)
                """,
                (ws_id, ws_name, True, scenario_slug, now_utc),
            )
            conn.execute(
                """
                INSERT INTO workspace_memberships (workspace_id, actor_id, role, created_at, revoked_at)
                VALUES (?, ?, 'owner', ?, NULL)
                """,
                (ws_id, actor_id, now_utc),
            )

            off_bakso_id = f"off_{uuid.uuid4().hex[:12]}"
            off_beras_id = f"off_{uuid.uuid4().hex[:12]}"
            off_jasa_id = f"off_{uuid.uuid4().hex[:12]}"

            demo_offerings = [
                (off_bakso_id, "Bakso Urat", "goods", 15000, "pcs", True, "WA"),
                (off_beras_id, "Beras Medium", "goods", 14500, "kg", True, "WA"),
                (off_jasa_id, "Jasa Katering Acara", "service", 500000, "sesi", False, None),
            ]
            for oid, oname, otype, oprice, ounit, req_stk, val_method in demo_offerings:
                conn.execute(
                    """
                    INSERT INTO offerings (
                        offering_id, workspace_id, name, offering_type, unit_price_idr,
                        unit, requires_stock_movement, valuation_method,
                        tax_status, tax_reason, tax_amount, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'not_assessed', ?, NULL, ?)
                    """,
                    (oid, ws_id, oname, otype, oprice, ounit, req_stk, val_method, DEFAULT_TAX_REASON, now_utc),
                )
                _record_audit(
                    conn,
                    ws_id,
                    actor_id,
                    "offering.created",
                    "offering",
                    oid,
                    {"offering_id": oid, "name": oname, "offering_type": otype, "unit_price_idr": oprice, "unit": ounit},
                )

            # Purchase 1: Bakso Urat 10 pcs @ Rp9.000 = Rp90.000 (cash out Rp90.000)
            pur1_id = f"pur_{uuid.uuid4().hex[:12]}"
            bat1_id = f"bat_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO purchases (
                    purchase_id, workspace_id, offering_id, qty, total_cost_idr,
                    payment_method, occurred_at, recorded_at
                ) VALUES (?, ?, ?, '10', 90000, 'cash', ?, ?)
                """,
                (pur1_id, ws_id, off_bakso_id, t1, now_utc),
            )
            conn.execute(
                """
                INSERT INTO inventory_batches (
                    batch_id, workspace_id, offering_id, purchase_id, qty_initial, qty_remaining,
                    total_cost_idr, occurred_at, recorded_at
                ) VALUES (?, ?, ?, ?, '10', '6', 90000, ?, ?)
                """,
                (bat1_id, ws_id, off_bakso_id, pur1_id, t1, now_utc),
            )
            conn.execute(
                """
                INSERT INTO stock_movements (
                    movement_id, workspace_id, offering_id, movement_type, qty_delta,
                    unit_cost_idr, total_cost_idr, reference_type, reference_id, occurred_at, recorded_at
                ) VALUES (?, ?, ?, 'purchase_in', '10', '9000', 90000, 'purchase', ?, ?, ?)
                """,
                (f"mov_{uuid.uuid4().hex[:12]}", ws_id, off_bakso_id, pur1_id, t1, now_utc),
            )
            conn.execute(
                """
                INSERT INTO cash_movements (
                    cash_id, workspace_id, direction, amount_idr, reference_type, reference_id, occurred_at, recorded_at
                ) VALUES (?, ?, 'out', 90000, 'purchase', ?, ?, ?)
                """,
                (f"csh_{uuid.uuid4().hex[:12]}", ws_id, pur1_id, t1, now_utc),
            )
            _record_audit(
                conn,
                ws_id,
                actor_id,
                "purchase.created",
                "purchase",
                pur1_id,
                {"purchase_id": pur1_id, "offering_id": off_bakso_id, "qty": "10", "total_cost_idr": 90000},
            )

            # Purchase 2: Beras Medium 10 kg @ Rp12.000 = Rp120.000 (cash out Rp120.000)
            pur2_id = f"pur_{uuid.uuid4().hex[:12]}"
            bat2_id = f"bat_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO purchases (
                    purchase_id, workspace_id, offering_id, qty, total_cost_idr,
                    payment_method, occurred_at, recorded_at
                ) VALUES (?, ?, ?, '10', 120000, 'cash', ?, ?)
                """,
                (pur2_id, ws_id, off_beras_id, t2, now_utc),
            )
            conn.execute(
                """
                INSERT INTO inventory_batches (
                    batch_id, workspace_id, offering_id, purchase_id, qty_initial, qty_remaining,
                    total_cost_idr, occurred_at, recorded_at
                ) VALUES (?, ?, ?, ?, '10', '10', 120000, ?, ?)
                """,
                (bat2_id, ws_id, off_beras_id, pur2_id, t2, now_utc),
            )
            conn.execute(
                """
                INSERT INTO stock_movements (
                    movement_id, workspace_id, offering_id, movement_type, qty_delta,
                    unit_cost_idr, total_cost_idr, reference_type, reference_id, occurred_at, recorded_at
                ) VALUES (?, ?, ?, 'purchase_in', '10', '12000', 120000, 'purchase', ?, ?, ?)
                """,
                (f"mov_{uuid.uuid4().hex[:12]}", ws_id, off_beras_id, pur2_id, t2, now_utc),
            )
            conn.execute(
                """
                INSERT INTO cash_movements (
                    cash_id, workspace_id, direction, amount_idr, reference_type, reference_id, occurred_at, recorded_at
                ) VALUES (?, ?, 'out', 120000, 'purchase', ?, ?, ?)
                """,
                (f"csh_{uuid.uuid4().hex[:12]}", ws_id, pur2_id, t2, now_utc),
            )
            _record_audit(
                conn,
                ws_id,
                actor_id,
                "purchase.created",
                "purchase",
                pur2_id,
                {"purchase_id": pur2_id, "offering_id": off_beras_id, "qty": "10", "total_cost_idr": 120000},
            )

            # Sale 1: Bakso Urat 4 pcs = Rp60.000 (HPP Rp36.000, gross profit Rp24.000)
            sale_id = f"sal_{uuid.uuid4().hex[:12]}"
            line_id = f"lin_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO sales (
                    sale_id, workspace_id, total_revenue_idr, total_cogs_idr, cogs_status,
                    policy_version, tax_status, tax_reason, occurred_at, recorded_at
                ) VALUES (?, ?, 60000, 36000, 'assessed', ?, 'not_assessed', ?, ?, ?)
                """,
                (sale_id, ws_id, POLICY_VERSION, DEFAULT_TAX_REASON, t3, now_utc),
            )
            conn.execute(
                """
                INSERT INTO sale_lines (
                    line_id, sale_id, workspace_id, offering_id, offering_type,
                    qty, revenue_idr, cogs_idr, cost_status
                ) VALUES (?, ?, ?, ?, 'goods', '4', 60000, 36000, 'assessed')
                """,
                (line_id, sale_id, ws_id, off_bakso_id),
            )
            conn.execute(
                """
                INSERT INTO stock_movements (
                    movement_id, workspace_id, offering_id, movement_type, qty_delta,
                    unit_cost_idr, total_cost_idr, reference_type, reference_id, occurred_at, recorded_at
                ) VALUES (?, ?, ?, 'sale_out', '-4', '9000', 36000, 'sale', ?, ?, ?)
                """,
                (f"mov_{uuid.uuid4().hex[:12]}", ws_id, off_bakso_id, sale_id, t3, now_utc),
            )
            conn.execute(
                """
                INSERT INTO cash_movements (
                    cash_id, workspace_id, direction, amount_idr, reference_type, reference_id, occurred_at, recorded_at
                ) VALUES (?, ?, 'in', 60000, 'sale', ?, ?, ?)
                """,
                (f"csh_{uuid.uuid4().hex[:12]}", ws_id, sale_id, t3, now_utc),
            )

            # Ending pools: Bakso 6 pcs / Rp54.000; Beras 10 kg / Rp120.000 -> total Rp174.000
            conn.execute(
                "INSERT INTO inventory_pools (workspace_id, offering_id, qty_on_hand, total_value_idr) VALUES (?, ?, '6', 54000)",
                (ws_id, off_bakso_id),
            )
            conn.execute(
                "INSERT INTO inventory_pools (workspace_id, offering_id, qty_on_hand, total_value_idr) VALUES (?, ?, '10', 120000)",
                (ws_id, off_beras_id),
            )

            _record_audit(
                conn,
                ws_id,
                actor_id,
                "sale.created",
                "sale",
                sale_id,
                {"sale_id": sale_id, "total_revenue_idr": 60000, "total_cogs_idr": 36000, "gross_profit_idr": 24000},
            )
            ws_dict = {
                "workspace_id": ws_id,
                "name": ws_name,
                "business_type": "umkm_hybrid",
                "currency": "IDR",
                "timezone": "Asia/Jakarta",
                "is_demo": True,
                "demo_slug": scenario_slug,
                "created_at": now_utc,
            }
            _record_audit(
                conn,
                ws_id,
                actor_id,
                "demo.bootstrapped",
                "workspace",
                ws_id,
                {"scenario_slug": scenario_slug, "demo_date": demo_date},
            )

            return 201, {
                "workspace": ws_dict,
                "created": True,
                "idempotent_replay": False,
                "scenario_slug": scenario_slug,
                "demo_date": demo_date,
            }

    def simulate_price(
        self,
        workspace_id: str,
        actor_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Read-only price & discount simulation; never mutates offerings, stock, or ledger."""
        with self._tx() as conn:
            self._assert_workspace_access(conn, workspace_id, actor_id)
            validated = validate_simulation_input(payload)
            offering_name: str | None = None
            offering_type: str | None = None
            base_price_idr = validated.selling_price_idr
            unit_cost_idr = validated.unit_cost_idr

            if validated.offering_id is not None:
                off = conn.execute(
                    "SELECT * FROM offerings WHERE workspace_id = ? AND offering_id = ?",
                    (workspace_id, validated.offering_id),
                ).fetchone()
                if not off:
                    raise DomainError(
                        404,
                        "offering_not_found",
                        f"Offering {validated.offering_id} tidak ditemukan.",
                    )
                offering_name = off["name"]
                offering_type = off["offering_type"]
                if base_price_idr is None:
                    base_price_idr = int(off["unit_price_idr"])
                if unit_cost_idr is None and off["requires_stock_movement"]:
                    pool = conn.execute(
                        "SELECT qty_on_hand, total_value_idr FROM inventory_pools WHERE workspace_id = ? AND offering_id = ?",
                        (workspace_id, validated.offering_id),
                    ).fetchone()
                    if pool and Decimal(pool["qty_on_hand"]) > 0:
                        unit_cost_idr = round_idr(
                            Decimal(pool["total_value_idr"]) / Decimal(pool["qty_on_hand"])
                        )

            assert base_price_idr is not None
            result = compute_price_simulation(
                selling_price_idr=base_price_idr,
                discount_percent=validated.discount_percent,
                unit_cost_idr=unit_cost_idr,
            )
            return {
                "workspace_id": workspace_id,
                "offering_id": validated.offering_id,
                "offering_name": offering_name,
                "offering_type": offering_type,
                **result,
                "read_only": True,
                "simulation_note": "Simulasi bersifat read-only dan tidak mengubah offering, stok, atau ledger.",
            }

    def list_benchmark_snapshots(
        self,
        workspace_id: str,
        actor_id: str,
    ) -> list[dict[str, Any]]:
        """List attributed market price benchmark snapshots for a workspace."""
        with self._tx() as conn:
            self._assert_workspace_access(conn, workspace_id, actor_id)
            return [dict(item) for item in BENCHMARK_SNAPSHOTS]

    def compare_price_benchmark(
        self,
        workspace_id: str,
        actor_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Read-only price benchmark comparison; never mutates offerings, stock, or ledger."""
        with self._tx() as conn:
            self._assert_workspace_access(conn, workspace_id, actor_id)
            offering_id, observation = validate_benchmark_input(payload)
            off = conn.execute(
                "SELECT * FROM offerings WHERE workspace_id = ? AND offering_id = ?",
                (workspace_id, offering_id),
            ).fetchone()
            if not off:
                raise DomainError(
                    404,
                    "offering_not_found",
                    f"Offering {offering_id} tidak ditemukan.",
                )
            result = compute_price_benchmark(
                offering_unit=off["unit"],
                offering_unit_price_idr=int(off["unit_price_idr"]),
                observation=observation,
            )
            return {
                "workspace_id": workspace_id,
                "offering_id": offering_id,
                "offering_name": off["name"],
                "offering_type": off["offering_type"],
                **result,
                "read_only": True,
                "catalog_unchanged": True,
                "benchmark_note": "Benchmark bersifat read-only dan tidak mengubah harga katalog (unit_price_idr), stok, atau ledger.",
            }

    def get_ai_review_config(
        self,
        workspace_id: str,
        actor_id: str | None,
    ) -> dict[str, Any]:
        from app.ai_review import get_ai_provider_config_status

        with self._tx() as conn:
            self._assert_workspace_access(conn, workspace_id, actor_id)
        return {
            "workspace_id": workspace_id,
            **get_ai_provider_config_status(),
        }

    def run_daily_ai_review(
        self,
        workspace_id: str,
        actor_id: str | None,
        payload: dict[str, Any] | None = None,
        provider_callable: Any = None,
    ) -> dict[str, Any]:
        from app.ai_review import STUB_MODES, execute_ai_review

        with self._tx() as conn:
            self._assert_workspace_access(conn, workspace_id, actor_id)

        body = payload if isinstance(payload, dict) else {}
        date_str = body.get("date")
        if date_str is not None and not isinstance(date_str, str):
            raise DomainError(422, "invalid_date", "Format tanggal harus string YYYY-MM-DD.")

        import math
        import os

        stub_mode = body.get("stub_mode") or None
        if stub_mode is not None:
            if os.environ.get("MARKETSTUDIO_ENV") == "production" and os.environ.get("MARKETSTUDIO_ENABLE_AI_STUBS") != "1":
                raise DomainError(403, "stub_disabled", "Stub mode dinonaktifkan di production.")
            if stub_mode not in STUB_MODES:
                raise DomainError(
                    422,
                    "invalid_stub_mode",
                    f"stub_mode tidak dikenal. Pilihan: {', '.join(sorted(STUB_MODES))}.",
                )

        raw_timeout = body.get("timeout_seconds", 8.0)
        if isinstance(raw_timeout, bool):
            raise DomainError(422, "invalid_timeout", "timeout_seconds harus berupa angka.")
        try:
            timeout_seconds = float(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise DomainError(422, "invalid_timeout", "timeout_seconds harus berupa angka.") from exc
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0 or timeout_seconds > 30:
            raise DomainError(422, "invalid_timeout", "timeout_seconds harus di antara 0 dan 30 detik.")

        report = self.get_daily_report(workspace_id, actor_id, date_str=date_str)
        result = execute_ai_review(
            report,
            stub_mode=stub_mode,
            timeout_seconds=timeout_seconds,
            provider_callable=provider_callable,
        )
        return {
            "workspace_id": workspace_id,
            "read_only": True,
            "ledger_unchanged": True,
            **result,
        }

    # --- Creative Studio (#42): Licensed Local Assets, Poster Drafts, Preview & Export ---

    def _assert_poster_access(self, conn: Any, workspace_id: str, actor_id: str | None) -> None:
        self._assert_workspace_access(conn, workspace_id, actor_id)
        if self.backend != "sqlite":
            raise DomainError(
                503,
                "poster_backend_unavailable",
                "Creative Studio tersedia pada penyimpanan SQLite lokal.",
            )

    def _resolve_asset_record(
        self,
        conn: Any,
        workspace_id: str,
        asset_id: str,
    ) -> dict[str, Any]:
        if asset_id in BUILTIN_ASSET_MAP:
            return dict(BUILTIN_ASSET_MAP[asset_id])
        row = conn.execute(
            "SELECT * FROM creative_assets WHERE workspace_id = ? AND asset_id = ?",
            (workspace_id, asset_id),
        ).fetchone()
        if not row:
            raise DomainError(
                404,
                "asset_not_found",
                f"Aset '{asset_id}' tidak ditemukan pada workspace ini.",
                {"asset_id": "Aset tidak ditemukan pada workspace aktif."},
            )
        provenance: dict[str, Any] = {}
        try:
            parsed = json.loads(row["asset_provenance_json"])
            if isinstance(parsed, dict):
                provenance = parsed
        except (TypeError, ValueError):
            provenance = {}
        return {
            "asset_id": row["asset_id"],
            "workspace_id": row["workspace_id"],
            "title": row["title"],
            "mime_type": row["mime_type"],
            "file_path": row["file_path"],
            "filename": Path(row["file_path"]).name,
            "asset_source": row["asset_source"],
            "asset_license": row["asset_license"],
            "license_status": row["license_status"],
            "attribution_text": row["attribution_text"],
            "asset_provenance": provenance,
            "is_builtin": False,
            "created_at": row["created_at"],
        }

    def _row_to_poster_draft(self, row: Any) -> dict[str, Any]:
        copy_prov = None
        if row["copy_provenance_json"]:
            try:
                copy_prov = json.loads(row["copy_provenance_json"])
            except (TypeError, ValueError):
                copy_prov = None
        asset_prov: dict[str, Any] = {}
        try:
            parsed_ap = json.loads(row["asset_provenance_json"])
            if isinstance(parsed_ap, dict):
                asset_prov = parsed_ap
        except (TypeError, ValueError):
            asset_prov = {}
        version = int(row["version"])
        last_prev_ver = (
            int(row["last_previewed_version"])
            if row["last_previewed_version"] is not None
            else None
        )
        preview_synced = (
            last_prev_ver == version
            and row["last_previewed_hash"] == row["revision_hash"]
        )
        return {
            "draft_id": row["draft_id"],
            "workspace_id": row["workspace_id"],
            "offering_id": row["offering_id"],
            "title": row["title"],
            "headline": row["headline"],
            "caption": row["caption"],
            "cta_text": row["cta_text"],
            "price_label": row["price_label"],
            "copy_source": row["copy_source"],
            "copy_provenance": copy_prov,
            "asset_id": row["asset_id"],
            "asset_source": row["asset_source"],
            "asset_license": row["asset_license"],
            "asset_provenance": asset_prov,
            "version": version,
            "revision_hash": row["revision_hash"],
            "status": row["status"],
            "published": False,
            "last_previewed_version": last_prev_ver,
            "last_previewed_hash": row["last_previewed_hash"],
            "last_previewed_at": row["last_previewed_at"],
            "preview_synced": preview_synced,
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_creative_assets(
        self,
        workspace_id: str,
        actor_id: str | None,
    ) -> list[dict[str, Any]]:
        """List verified licensed local sample assets plus workspace-scoped custom assets."""
        with self._tx() as conn:
            self._assert_poster_access(conn, workspace_id, actor_id)
            items = [
                {
                    **item,
                    "asset_provenance": dict(item["asset_provenance"]),
                }
                for item in LICENSED_LOCAL_ASSETS
            ]
            rows = conn.execute(
                "SELECT * FROM creative_assets WHERE workspace_id = ? ORDER BY created_at DESC",
                (workspace_id,),
            ).fetchall()
            for r in rows:
                items.append(self._resolve_asset_record(conn, workspace_id, r["asset_id"]))
            return items

    def list_poster_drafts(
        self,
        workspace_id: str,
        actor_id: str | None,
    ) -> list[dict[str, Any]]:
        """List workspace-scoped poster drafts."""
        with self._tx() as conn:
            self._assert_poster_access(conn, workspace_id, actor_id)
            rows = conn.execute(
                """
                SELECT * FROM poster_drafts
                WHERE workspace_id = ?
                ORDER BY updated_at DESC, created_at DESC
                """,
                (workspace_id,),
            ).fetchall()
            return [self._row_to_poster_draft(r) for r in rows]

    def get_poster_draft(
        self,
        workspace_id: str,
        draft_id: str,
        actor_id: str | None,
    ) -> dict[str, Any]:
        """Fetch one workspace-scoped poster draft."""
        with self._tx() as conn:
            self._assert_poster_access(conn, workspace_id, actor_id)
            row = conn.execute(
                "SELECT * FROM poster_drafts WHERE workspace_id = ? AND draft_id = ?",
                (workspace_id, draft_id),
            ).fetchone()
            if not row:
                raise DomainError(
                    404,
                    "poster_draft_not_found",
                    "Draft poster tidak ditemukan pada workspace ini.",
                )
            return self._row_to_poster_draft(row)

    def _insert_poster_draft(
        self,
        conn: Any,
        *,
        workspace_id: str,
        actor_id: str,
        cleaned: dict[str, Any],
        asset_record: dict[str, Any],
    ) -> dict[str, Any]:
        draft_id = f"drf_{uuid.uuid4().hex[:12]}"
        now_utc = _utc_now()
        asset_prov = {
            **dict(asset_record.get("asset_provenance") or {}),
            "attribution_text": asset_record["attribution_text"],
            "license_status": asset_record["license_status"],
            "mime_type": asset_record["mime_type"],
        }
        base_draft = {
            "draft_id": draft_id,
            "workspace_id": workspace_id,
            "offering_id": cleaned["offering_id"],
            "title": cleaned["title"],
            "headline": cleaned["headline"],
            "caption": cleaned["caption"],
            "cta_text": cleaned["cta_text"],
            "price_label": cleaned["price_label"],
            "copy_source": cleaned["copy_source"],
            "asset_id": asset_record["asset_id"],
            "asset_source": asset_record["asset_source"],
            "asset_license": asset_record["asset_license"],
            "version": 1,
        }
        revision_hash = compute_draft_revision_hash(base_draft)
        copy_prov_json = (
            json.dumps(cleaned["copy_provenance"], sort_keys=True)
            if cleaned.get("copy_provenance") is not None
            else None
        )
        asset_prov_json = json.dumps(asset_prov, sort_keys=True)

        conn.execute(
            """
            INSERT INTO poster_drafts (
                draft_id, workspace_id, offering_id, title, headline, caption,
                cta_text, price_label, copy_source, copy_provenance_json,
                asset_id, asset_source, asset_license, asset_provenance_json,
                version, revision_hash, status,
                last_previewed_version, last_previewed_hash, last_previewed_at,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'draft', NULL, NULL, NULL, ?, ?, ?)
            """,
            (
                draft_id,
                workspace_id,
                cleaned["offering_id"],
                cleaned["title"],
                cleaned["headline"],
                cleaned["caption"],
                cleaned["cta_text"],
                cleaned["price_label"],
                cleaned["copy_source"],
                copy_prov_json,
                asset_record["asset_id"],
                asset_record["asset_source"],
                asset_record["asset_license"],
                asset_prov_json,
                revision_hash,
                actor_id,
                now_utc,
                now_utc,
            ),
        )
        row = conn.execute(
            "SELECT * FROM poster_drafts WHERE workspace_id = ? AND draft_id = ?",
            (workspace_id, draft_id),
        ).fetchone()
        result = self._row_to_poster_draft(row)
        _record_audit(
            conn,
            workspace_id,
            actor_id,
            "poster_draft.created",
            "poster_draft",
            draft_id,
            {
                "draft_id": draft_id,
                "version": 1,
                "revision_hash": revision_hash,
                "asset_id": asset_record["asset_id"],
                "asset_license": asset_record["asset_license"],
                "status": "draft",
            },
        )
        return result

    def _assert_verified_asset_metadata(self, asset_record: dict[str, Any]) -> None:
        if (
            str(asset_record.get("license_status") or "").lower() != "verified"
            or not str(asset_record.get("asset_license") or "").strip()
            or not str(asset_record.get("asset_source") or "").strip()
            or not str(asset_record.get("attribution_text") or "").strip()
        ):
            raise DomainError(
                422,
                "unlicensed_asset",
                "Aset poster belum memiliki lisensi terverifikasi dan tidak dapat dipakai.",
                {"asset_id": "Aset harus memiliki lisensi terverifikasi."},
            )

    def create_poster_draft(
        self,
        workspace_id: str,
        actor_id: str | None,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        actor: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """Create a persisted draft poster bound to a verified licensed asset (status='draft')."""
        with self._tx(immediate=True) as conn:
            self._assert_poster_access(conn, workspace_id, actor_id)
            assert actor_id is not None
            body = payload if isinstance(payload, dict) else {}
            cleaned = validate_poster_draft_input(body, partial=False)
            req_hash = _hash_payload(body)

            replay = self._check_idempotency(
                conn, workspace_id, "create_poster_draft", idempotency_key, req_hash
            )
            if replay:
                return replay

            if cleaned["offering_id"] is not None:
                off = conn.execute(
                    "SELECT offering_id FROM offerings WHERE workspace_id = ? AND offering_id = ?",
                    (workspace_id, cleaned["offering_id"]),
                ).fetchone()
                if not off:
                    raise DomainError(
                        404,
                        "offering_not_found",
                        "Offering tidak ditemukan pada workspace ini.",
                        {"offering_id": "Offering tidak ditemukan pada workspace ini."},
                    )

            asset_record = self._resolve_asset_record(conn, workspace_id, cleaned["asset_id"])
            self._assert_verified_asset_metadata(asset_record)

            result = self._insert_poster_draft(
                conn,
                workspace_id=workspace_id,
                actor_id=actor or actor_id,
                cleaned=cleaned,
                asset_record=asset_record,
            )
            self._save_idempotency(
                conn,
                workspace_id,
                "create_poster_draft",
                idempotency_key,
                req_hash,
                201,
                result,
                result["created_at"],
            )
            return 201, result

    def create_sample_poster_draft(
        self,
        workspace_id: str,
        actor_id: str | None,
        idempotency_key: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """One-click creation of a sample poster draft using workspace offering + licensed CC0 asset."""
        with self._tx(immediate=True) as conn:
            self._assert_poster_access(conn, workspace_id, actor_id)
            assert actor_id is not None
            req_hash = _hash_payload({"sample": True})
            replay = self._check_idempotency(
                conn, workspace_id, "create_sample_poster_draft", idempotency_key, req_hash
            )
            if replay:
                return replay

            off = conn.execute(
                "SELECT * FROM offerings WHERE workspace_id = ? ORDER BY created_at ASC LIMIT 1",
                (workspace_id,),
            ).fetchone()

            if off:
                name_lower = str(off["name"]).lower()
                if "beras" in name_lower:
                    asset_id = "asset_beras_harvest_v1"
                elif off["offering_type"] == "service" or "katering" in name_lower:
                    asset_id = "asset_catering_tray_v1"
                else:
                    asset_id = "asset_bakso_bowl_v1"
                price_fmt = f"Rp {int(off['unit_price_idr']):,}".replace(",", ".")
                cleaned = {
                    "offering_id": off["offering_id"],
                    "title": f"Promo {off['name']}"[:120],
                    "headline": f"Sedia {off['name']} Siap Pesan"[:140],
                    "caption": (
                        f"{off['name']} siap dipesan dengan harga {price_fmt} per {off['unit']}. "
                        "Hubungi kami untuk pemesanan."
                    ),
                    "cta_text": "Pesan Sekarang",
                    "price_label": f"{price_fmt} / {off['unit']}"[:60],
                    "copy_source": "sample",
                    "copy_provenance": {
                        "source": "workspace_offering_sample",
                        "offering_id": off["offering_id"],
                    },
                    "asset_id": asset_id,
                }
            else:
                cleaned = {
                    "offering_id": None,
                    "title": "Promo Bakso Urat Spesial",
                    "headline": "Hangat, Gurih & Siap Saji",
                    "caption": (
                        "Nikmati Bakso Urat Spesial yang hangat dan gurih. Pesan langsung di outlet."
                    ),
                    "cta_text": "Pesan di Outlet",
                    "price_label": "Rp 15.000 / pcs",
                    "copy_source": "sample",
                    "copy_provenance": {"source": "synthetic_poster_sample"},
                    "asset_id": "asset_bakso_bowl_v1",
                }

            asset_record = self._resolve_asset_record(conn, workspace_id, cleaned["asset_id"])
            result = self._insert_poster_draft(
                conn,
                workspace_id=workspace_id,
                actor_id=actor_id,
                cleaned=cleaned,
                asset_record=asset_record,
            )
            self._save_idempotency(
                conn,
                workspace_id,
                "create_sample_poster_draft",
                idempotency_key,
                req_hash,
                201,
                result,
                result["created_at"],
            )
            return 201, result

    def update_poster_draft(
        self,
        workspace_id: str,
        draft_id: str,
        actor_id: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a poster draft, bumping version and invalidating prior preview lock."""
        with self._tx(immediate=True) as conn:
            self._assert_poster_access(conn, workspace_id, actor_id)
            assert actor_id is not None
            row = conn.execute(
                "SELECT * FROM poster_drafts WHERE workspace_id = ? AND draft_id = ?",
                (workspace_id, draft_id),
            ).fetchone()
            if not row:
                raise DomainError(
                    404,
                    "poster_draft_not_found",
                    "Draft poster tidak ditemukan pada workspace ini.",
                )

            body = payload if isinstance(payload, dict) else {}
            cleaned = validate_poster_draft_input(body, partial=True)
            cur_version = int(row["version"])
            if "expected_version" in cleaned and cleaned["expected_version"] != cur_version:
                raise DomainError(
                    409,
                    "draft_version_conflict",
                    f"Versi draft telah berubah (tersimpan v{cur_version}, dikirim v{cleaned['expected_version']}). Muat ulang draft terlebih dahulu.",
                )

            offering_id = cleaned["offering_id"] if "offering_id" in cleaned else row["offering_id"]
            if offering_id is not None:
                off = conn.execute(
                    "SELECT offering_id FROM offerings WHERE workspace_id = ? AND offering_id = ?",
                    (workspace_id, offering_id),
                ).fetchone()
                if not off:
                    raise DomainError(
                        404,
                        "offering_not_found",
                        "Offering tidak ditemukan pada workspace ini.",
                        {"offering_id": "Offering tidak ditemukan pada workspace ini."},
                    )

            asset_id = cleaned["asset_id"] if "asset_id" in cleaned else row["asset_id"]
            asset_record = self._resolve_asset_record(conn, workspace_id, asset_id)
            self._assert_verified_asset_metadata(asset_record)

            new_version = cur_version + 1
            title = cleaned.get("title", row["title"])
            headline = cleaned.get("headline", row["headline"])
            caption = cleaned.get("caption", row["caption"])
            cta_text = cleaned.get("cta_text", row["cta_text"])
            price_label = cleaned.get("price_label", row["price_label"])
            copy_source = cleaned.get("copy_source", row["copy_source"])
            copy_prov_json = (
                json.dumps(cleaned["copy_provenance"], sort_keys=True)
                if "copy_provenance" in cleaned and cleaned["copy_provenance"] is not None
                else (None if "copy_provenance" in cleaned else row["copy_provenance_json"])
            )
            asset_prov = {
                **dict(asset_record.get("asset_provenance") or {}),
                "attribution_text": asset_record["attribution_text"],
                "license_status": asset_record["license_status"],
                "mime_type": asset_record["mime_type"],
            }
            new_hash = compute_draft_revision_hash(
                {
                    "draft_id": draft_id,
                    "workspace_id": workspace_id,
                    "offering_id": offering_id,
                    "title": title,
                    "headline": headline,
                    "caption": caption,
                    "cta_text": cta_text,
                    "price_label": price_label,
                    "copy_source": copy_source,
                    "asset_id": asset_record["asset_id"],
                    "asset_source": asset_record["asset_source"],
                    "asset_license": asset_record["asset_license"],
                    "version": new_version,
                }
            )
            now_utc = _utc_now()
            conn.execute(
                """
                UPDATE poster_drafts SET
                    offering_id = ?, title = ?, headline = ?, caption = ?,
                    cta_text = ?, price_label = ?, copy_source = ?, copy_provenance_json = ?,
                    asset_id = ?, asset_source = ?, asset_license = ?, asset_provenance_json = ?,
                    version = ?, revision_hash = ?, status = 'draft',
                    last_previewed_version = NULL, last_previewed_hash = NULL, last_previewed_at = NULL,
                    last_previewed_format = NULL, last_previewed_sha256 = NULL,
                    updated_at = ?
                WHERE workspace_id = ? AND draft_id = ?
                """,
                (
                    offering_id,
                    title,
                    headline,
                    caption,
                    cta_text,
                    price_label,
                    copy_source,
                    copy_prov_json,
                    asset_record["asset_id"],
                    asset_record["asset_source"],
                    asset_record["asset_license"],
                    json.dumps(asset_prov, sort_keys=True),
                    new_version,
                    new_hash,
                    now_utc,
                    workspace_id,
                    draft_id,
                ),
            )
            updated_row = conn.execute(
                "SELECT * FROM poster_drafts WHERE workspace_id = ? AND draft_id = ?",
                (workspace_id, draft_id),
            ).fetchone()
            _record_audit(
                conn,
                workspace_id,
                actor_id,
                "poster_draft.updated",
                "poster_draft",
                draft_id,
                {
                    "draft_id": draft_id,
                    "version": new_version,
                    "revision_hash": new_hash,
                    "asset_id": asset_record["asset_id"],
                    "status": "draft",
                },
            )
            return self._row_to_poster_draft(updated_row)

    def preview_poster_draft(
        self,
        workspace_id: str,
        draft_id: str,
        actor_id: str | None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Verify licensed asset, render preview for current version, and lock preview revision."""
        with self._tx(immediate=True) as conn:
            self._assert_poster_access(conn, workspace_id, actor_id)
            assert actor_id is not None
            row = conn.execute(
                "SELECT * FROM poster_drafts WHERE workspace_id = ? AND draft_id = ?",
                (workspace_id, draft_id),
            ).fetchone()
            if not row:
                raise DomainError(
                    404,
                    "poster_draft_not_found",
                    "Draft poster tidak ditemukan pada workspace ini.",
                )

            fmt, sim_fail = validate_preview_request(payload)
            ws_row = conn.execute(
                "SELECT name FROM workspaces WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
            ws_name = ws_row["name"] if ws_row else "MarketStudio"

            asset_record = self._resolve_asset_record(conn, workspace_id, row["asset_id"])
            loaded_asset = load_and_verify_asset(
                asset_record,
                self.creative_assets_dir,
                simulate_failure=sim_fail,
            )

            draft_dict = self._row_to_poster_draft(row)
            content, mime, _, digest = render_poster_artifact(draft_dict, loaded_asset, ws_name, fmt)

            now_utc = _utc_now()
            conn.execute(
                """
                UPDATE poster_drafts
                SET last_previewed_version = ?, last_previewed_hash = ?, last_previewed_at = ?,
                    last_previewed_format = ?, last_previewed_sha256 = ?
                WHERE workspace_id = ? AND draft_id = ?
                """,
                (draft_dict["version"], draft_dict["revision_hash"], now_utc, fmt, digest, workspace_id, draft_id),
            )
            updated_row = conn.execute(
                "SELECT * FROM poster_drafts WHERE workspace_id = ? AND draft_id = ?",
                (workspace_id, draft_id),
            ).fetchone()
            synced_draft = self._row_to_poster_draft(updated_row)

            _record_audit(
                conn,
                workspace_id,
                actor_id,
                "poster_draft.previewed",
                "poster_draft",
                draft_id,
                {
                    "draft_id": draft_id,
                    "version": synced_draft["version"],
                    "revision_hash": synced_draft["revision_hash"],
                    "preview_format": fmt,
                    "sha256": digest,
                    "asset_id": loaded_asset.asset_id,
                    "asset_license": loaded_asset.asset_license,
                    "status": "draft",
                },
            )

            data_url = f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"

            return {
                "workspace_id": workspace_id,
                "draft": synced_draft,
                "asset": {
                    "asset_id": loaded_asset.asset_id,
                    "title": loaded_asset.title,
                    "mime_type": loaded_asset.mime_type,
                    "asset_source": loaded_asset.asset_source,
                    "asset_license": loaded_asset.asset_license,
                    "license_status": loaded_asset.license_status,
                    "attribution_text": loaded_asset.attribution_text,
                    "asset_provenance": loaded_asset.asset_provenance,
                    "sha256": loaded_asset.sha256,
                    "width": loaded_asset.width,
                    "height": loaded_asset.height,
                },
                "preview_format": fmt,
                "preview_data_url": data_url,
                "preview_sha256": digest,
                "supported_formats": list(SUPPORTED_EXPORT_FORMATS),
                "publish_mutated": False,
                "ledger_unchanged": True,
            }

    def export_poster_draft(
        self,
        workspace_id: str,
        draft_id: str,
        actor_id: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Export poster bytes strictly matching the exact previewed draft_version without publishing."""
        with self._tx(immediate=True) as conn:
            self._assert_poster_access(conn, workspace_id, actor_id)
            assert actor_id is not None
            row = conn.execute(
                "SELECT * FROM poster_drafts WHERE workspace_id = ? AND draft_id = ?",
                (workspace_id, draft_id),
            ).fetchone()
            if not row:
                raise DomainError(
                    404,
                    "poster_draft_not_found",
                    "Draft poster tidak ditemukan pada workspace ini.",
                )

            fmt, expected_version, expected_hash, preview_sha256, sim_fail = validate_export_request(payload)
            cur_version = int(row["version"])
            if cur_version != expected_version or (
                expected_hash is not None and row["revision_hash"] != expected_hash
            ):
                raise DomainError(
                    409,
                    "draft_version_conflict",
                    (
                        f"Versi draft tidak cocok dengan pratinjau (diminta v{expected_version}, "
                        f"tersimpan v{cur_version}). Muat pratinjau ulang sebelum mengekspor."
                    ),
                )

            if (
                row["last_previewed_version"] != cur_version
                or row["last_previewed_hash"] != row["revision_hash"]
                or row["last_previewed_format"] != fmt
            ):
                raise DomainError(
                    409,
                    "preview_required",
                    "Tampilkan pratinjau untuk versi draft dan format ekspor yang dipilih.",
                )

            if row["status"] != "draft":
                raise DomainError(
                    409,
                    "invalid_draft_status",
                    "Ekspor hanya diperbolehkan untuk draft berstatus 'draft'.",
                )

            ws_row = conn.execute(
                "SELECT name FROM workspaces WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
            ws_name = ws_row["name"] if ws_row else "MarketStudio"

            asset_record = self._resolve_asset_record(conn, workspace_id, row["asset_id"])
            loaded_asset = load_and_verify_asset(
                asset_record,
                self.creative_assets_dir,
                simulate_failure=sim_fail,
            )

            draft_dict = self._row_to_poster_draft(row)
            content_bytes, content_type, filename, sha256_hex = render_poster_artifact(
                draft_dict, loaded_asset, ws_name, fmt
            )
            if sha256_hex != row["last_previewed_sha256"] or sha256_hex != preview_sha256:
                raise DomainError(
                    409,
                    "preview_content_changed",
                    "Isi poster berubah sejak pratinjau. Tampilkan pratinjau kembali sebelum mengekspor.",
                )

            _record_audit(
                conn,
                workspace_id,
                actor_id,
                "poster_draft.exported",
                "poster_draft",
                draft_id,
                {
                    "draft_id": draft_id,
                    "version": draft_dict["version"],
                    "revision_hash": draft_dict["revision_hash"],
                    "format": fmt,
                    "filename": filename,
                    "sha256": sha256_hex,
                    "byte_size": len(content_bytes),
                    "asset_id": loaded_asset.asset_id,
                    "asset_source": loaded_asset.asset_source,
                    "asset_license": loaded_asset.asset_license,
                    "status": "draft",
                    "publish_mutated": False,
                },
            )

            return {
                "workspace_id": workspace_id,
                "draft": draft_dict,
                "asset": {
                    "asset_id": loaded_asset.asset_id,
                    "title": loaded_asset.title,
                    "mime_type": loaded_asset.mime_type,
                    "asset_source": loaded_asset.asset_source,
                    "asset_license": loaded_asset.asset_license,
                    "license_status": loaded_asset.license_status,
                    "attribution_text": loaded_asset.attribution_text,
                    "sha256": loaded_asset.sha256,
                },
                "format": fmt,
                "content_bytes": content_bytes,
                "content_type": content_type,
                "filename": filename,
                "sha256": sha256_hex,
                "publish_mutated": False,
                "ledger_unchanged": True,
            }

    def _assert_catalog_owner(self, conn: Any, workspace_id: str, actor_id: str) -> None:
        self._assert_poster_access(conn, workspace_id, actor_id)
        membership = conn.execute(
            """SELECT 1 FROM workspace_memberships WHERE workspace_id = ?
               AND actor_id = ? AND role = 'owner' AND revoked_at IS NULL""",
            (workspace_id, actor_id),
        ).fetchone()
        if not membership:
            raise DomainError(404, "workspace_not_found", "Workspace tidak ditemukan atau akses ditolak.")

    def _catalog_state(self, conn: Any, workspace_id: str) -> dict[str, Any]:
        rows = conn.execute(
            """SELECT version_id, state, public_token, selection_json, snapshot_json
               FROM catalog_versions WHERE workspace_id = ? AND state IN ('draft', 'active')""",
            (workspace_id,),
        ).fetchall()
        result = {"draft": None, "public_path": None}
        for row in rows:
            if row["state"] == "active":
                result["public_path"] = f'/katalog/{row["public_token"]}'
            else:
                result["draft"] = {
                    "version_id": row["version_id"],
                    "selection": json.loads(row["selection_json"]),
                    "html": render_catalog(json.loads(row["snapshot_json"])),
                }
        return result

    def get_catalog(self, workspace_id: str, actor_id: str) -> dict[str, Any]:
        with self._tx() as conn:
            self._assert_catalog_owner(conn, workspace_id, actor_id)
            return self._catalog_state(conn, workspace_id)

    def preview_catalog(self, workspace_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._tx(immediate=True) as conn:
            self._assert_catalog_owner(conn, workspace_id, actor_id)
            ids = payload.get("offering_ids")
            asset_id = payload.get("asset_id")
            if (not isinstance(ids, list) or not 1 <= len(ids) <= 100
                    or any(not isinstance(value, str) or not 1 <= len(value) <= 128 for value in ids)
                    or len(set(ids)) != len(ids)):
                raise DomainError(422, "invalid_selection", "Pilih 1–100 produk atau jasa yang berbeda.")
            if asset_id is not None and (not isinstance(asset_id, str) or not 1 <= len(asset_id) <= 128):
                raise DomainError(422, "invalid_selection", "Pilihan gambar tidak valid.")

            offerings = []
            for offering_id in ids:
                row = conn.execute(
                    """SELECT name, offering_type, unit, unit_price_idr FROM offerings
                       WHERE workspace_id = ? AND offering_id = ?""",
                    (workspace_id, offering_id),
                ).fetchone()
                if not row:
                    raise DomainError(404, "offering_not_found", "Produk atau jasa tidak ditemukan.")
                offerings.append(dict(row))

            asset = None
            if asset_id:
                record = self._resolve_asset_record(conn, workspace_id, asset_id)
                image = load_and_verify_asset(record, self.creative_assets_dir)
                # Re-encode pixels so source file metadata cannot become public.
                png = encode_png_rgb(image.width, image.height, image.rgb_bytes)
                asset = {
                    "image": base64.b64encode(png).decode("ascii"),
                    "title": image.title,
                    "license": image.asset_license,
                    "attribution": image.attribution_text,
                }

            workspace = conn.execute("SELECT name FROM workspaces WHERE workspace_id = ?", (workspace_id,)).fetchone()
            selection = {"offering_ids": ids, "asset_id": asset_id}
            snapshot = {"name": workspace["name"], "offerings": offerings, "asset": asset}
            conn.execute("DELETE FROM catalog_versions WHERE workspace_id = ? AND state = 'draft'", (workspace_id,))
            conn.execute(
                """INSERT INTO catalog_versions (version_id, workspace_id, state, selection_json, snapshot_json)
                   VALUES (?, ?, 'draft', ?, ?)""",
                (uuid.uuid4().hex, workspace_id, json.dumps(selection), json.dumps(snapshot)),
            )
            return self._catalog_state(conn, workspace_id)

    def publish_catalog(self, workspace_id: str, actor_id: str, version_id: Any) -> dict[str, Any]:
        with self._tx(immediate=True) as conn:
            self._assert_catalog_owner(conn, workspace_id, actor_id)
            if not isinstance(version_id, str):
                raise DomainError(422, "preview_required", "Tampilkan pratinjau katalog terlebih dahulu.")
            version = conn.execute(
                "SELECT state FROM catalog_versions WHERE workspace_id = ? AND version_id = ?",
                (workspace_id, version_id),
            ).fetchone()
            if not version or version["state"] == "revoked":
                raise DomainError(409, "stale_preview", "Pratinjau berubah. Tampilkan pratinjau baru.")
            if version["state"] == "draft":
                conn.execute("UPDATE catalog_versions SET state = 'revoked' WHERE workspace_id = ? AND state = 'active'",
                             (workspace_id,))
                conn.execute("UPDATE catalog_versions SET state = 'active', public_token = ? WHERE version_id = ?",
                             (secrets.token_urlsafe(24), version_id))
                _record_audit(conn, workspace_id, actor_id, "catalog.published", "catalog", version_id, {})
            return self._catalog_state(conn, workspace_id)

    def unpublish_catalog(self, workspace_id: str, actor_id: str, token: Any) -> dict[str, Any]:
        with self._tx(immediate=True) as conn:
            self._assert_catalog_owner(conn, workspace_id, actor_id)
            if not isinstance(token, str):
                raise DomainError(422, "invalid_catalog", "Versi publik tidak valid.")
            version = conn.execute(
                """SELECT version_id, state FROM catalog_versions
                   WHERE workspace_id = ? AND public_token = ?""",
                (workspace_id, token),
            ).fetchone()
            if not version:
                raise DomainError(404, "catalog_not_found", "Katalog tidak ditemukan.")
            if version["state"] == "active":
                conn.execute("UPDATE catalog_versions SET state = 'revoked' WHERE version_id = ?", (version["version_id"],))
                _record_audit(conn, workspace_id, actor_id, "catalog.unpublished", "catalog", version["version_id"], {})
            return self._catalog_state(conn, workspace_id)

    def get_public_catalog(self, token: str) -> str | None:
        if self.backend != "sqlite":
            return None
        with self._tx() as conn:
            row = conn.execute(
                "SELECT snapshot_json FROM catalog_versions WHERE public_token = ? AND state = 'active'", (token,)
            ).fetchone()
        return render_catalog(json.loads(row["snapshot_json"])) if row else None
