"""Application service layer: tenant isolation, idempotency, WA valuation, and audit."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.db import DEFAULT_DB_PATH, db_transaction
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

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path

    def create_session(self, actor_id: str, passcode: str = "") -> dict[str, Any]:
        clean_actor = actor_id.strip() if isinstance(actor_id, str) else ""
        expected = SYNTHETIC_PRINCIPALS.get(clean_actor)
        if not expected or not isinstance(passcode, str) or not hmac.compare_digest(passcode, expected):
            raise DomainError(401, "unauthenticated", "Kredensial principal tidak valid.")
        token = f"sess_{uuid.uuid4().hex}"
        created_at = _utc_now()
        with db_transaction(self.db_path, immediate=True) as conn:
            conn.execute(
                "INSERT INTO sessions (token, actor_id, created_at, revoked_at) VALUES (?, ?, ?, NULL)",
                (token, clean_actor, created_at),
            )
        return {"token": token, "actor_id": clean_actor, "created_at": created_at}

    def resolve_session(self, token: str | None) -> str:
        if not token:
            raise DomainError(401, "unauthenticated", "Session token wajib disertakan.")
        with db_transaction(self.db_path) as conn:
            row = conn.execute(
                "SELECT actor_id, revoked_at FROM sessions WHERE token = ?",
                (token,),
            ).fetchone()
            if not row or row["revoked_at"] is not None:
                raise DomainError(401, "unauthenticated", "Session tidak valid atau telah dicabut.")
            return str(row["actor_id"])

    def revoke_membership(self, workspace_id: str, actor_id: str) -> None:
        with db_transaction(self.db_path, immediate=True) as conn:
            conn.execute(
                "UPDATE workspace_memberships SET revoked_at = ? WHERE workspace_id = ? AND actor_id = ?",
                (_utc_now(), workspace_id, actor_id),
            )

    def list_workspaces(self, actor_id: str) -> list[dict[str, Any]]:
        with db_transaction(self.db_path) as conn:
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

        with db_transaction(self.db_path, immediate=True) as conn:
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
        with db_transaction(self.db_path) as conn:
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
        with db_transaction(self.db_path) as conn:
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
        with db_transaction(self.db_path, immediate=True) as conn:
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
                    1 if validated.requires_stock_movement else 0,
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
        with db_transaction(self.db_path, immediate=True) as conn:
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
            if max_mov and max_mov["max_ts"] and occurred_at < max_mov["max_ts"]:
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
        with db_transaction(self.db_path, immediate=True) as conn:
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
                    if max_mov and max_mov["max_ts"] and occurred_at < max_mov["max_ts"]:
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
                        WHERE workspace_id = ? AND offering_id = ? AND CAST(qty_remaining AS REAL) > 0
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
        with db_transaction(self.db_path) as conn:
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

        with db_transaction(self.db_path, immediate=True) as conn:
            existing = conn.execute(
                """
                SELECT w.* FROM workspaces w
                JOIN workspace_memberships m ON m.workspace_id = w.workspace_id
                WHERE m.actor_id = ? AND m.revoked_at IS NULL
                    AND w.is_demo = 1 AND w.demo_slug = ?
                ORDER BY w.created_at ASC LIMIT 1
                """,
                (actor_id, scenario_slug),
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
                ) VALUES (?, ?, 'umkm_hybrid', 'IDR', 'Asia/Jakarta', 1, ?, ?)
                """,
                (ws_id, ws_name, scenario_slug, now_utc),
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
                (off_bakso_id, "Bakso Urat", "goods", 15000, "pcs", 1, "WA"),
                (off_beras_id, "Beras Medium", "goods", 14500, "kg", 1, "WA"),
                (off_jasa_id, "Jasa Katering Acara", "service", 500000, "sesi", 0, None),
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
        with db_transaction(self.db_path) as conn:
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
        with db_transaction(self.db_path) as conn:
            self._assert_workspace_access(conn, workspace_id, actor_id)
            return [dict(item) for item in BENCHMARK_SNAPSHOTS]

    def compare_price_benchmark(
        self,
        workspace_id: str,
        actor_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Read-only price benchmark comparison; never mutates offerings, stock, or ledger."""
        with db_transaction(self.db_path) as conn:
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

        with db_transaction(self.db_path) as conn:
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

        with db_transaction(self.db_path) as conn:
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
