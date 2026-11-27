"""Application service layer: tenant isolation, idempotency, WA valuation, and audit."""

from __future__ import annotations

import hashlib
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
    DomainError,
    round_idr,
    validate_offering_input,
    validate_purchase_input,
    validate_sale_input,
    validate_workspace_input,
)

JAKARTA_TZ = ZoneInfo("Asia/Jakarta")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_occurred_at(raw: str | None) -> str:
    if not raw:
        return _utc_now()
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
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
    return {
        "offering_id": row["offering_id"],
        "workspace_id": row["workspace_id"],
        "name": row["name"],
        "offering_type": row["offering_type"],
        "unit_price_idr": row["unit_price_idr"],
        "currency": "IDR",
        "unit": row["unit"],
        "requires_stock_movement": bool(row["requires_stock_movement"]),
        "valuation_method": row["valuation_method"],
        "tax_status": row["tax_status"],
        "tax_reason": row["tax_reason"],
        "tax_amount": row["tax_amount"],
        "created_at": row["created_at"],
    }


def _row_to_workspace(row: Any) -> dict[str, Any]:
    return {
        "workspace_id": row["workspace_id"],
        "name": row["name"],
        "business_type": row["business_type"],
        "currency": row["currency"],
        "timezone": row["timezone"],
        "created_at": row["created_at"],
    }


class BaselineService:
    """Modular monolith service for Workspaces, Offerings, Purchases, Sales, and Reports."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path

    def list_workspaces(self) -> list[dict[str, Any]]:
        with db_transaction(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM workspaces ORDER BY created_at ASC").fetchall()
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
                    ("_global", "create_workspace", idempotency_key),
                ).fetchone()
                if existing:
                    if existing["request_hash"] != req_hash:
                        raise DomainError(
                            409,
                            "idempotency_conflict",
                            "Idempotency-Key sudah dipakai dengan payload berbeda.",
                        )
                    return existing["status_code"], json.loads(existing["response_body"])

            workspace_id = f"ws_{uuid.uuid4().hex[:12]}"
            created_at = _utc_now()
            conn.execute(
                """
                INSERT INTO workspaces (workspace_id, name, business_type, currency, timezone, created_at)
                VALUES (?, ?, ?, 'IDR', ?, ?)
                """,
                (workspace_id, validated.name, validated.business_type, validated.timezone, created_at),
            )
            result = {
                "workspace_id": workspace_id,
                "name": validated.name,
                "business_type": validated.business_type,
                "currency": "IDR",
                "timezone": validated.timezone,
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
                    ("_global", "create_workspace", idempotency_key, req_hash, 201, json.dumps(result), created_at),
                )
            return 201, result

    def _assert_workspace_access(
        self,
        conn: Any,
        workspace_id: str,
        caller_workspace_id: str | None,
        actor_status: str | None = None,
    ) -> None:
        if actor_status == "revoked":
            raise DomainError(403, "actor_revoked", "Akses aktor telah dicabut.")
        if not caller_workspace_id or caller_workspace_id != workspace_id:
            raise DomainError(
                403,
                "forbidden_workspace",
                "Akses lintas workspace ditolak (X-Workspace-Id tidak cocok).",
            )
        ws = conn.execute(
            "SELECT workspace_id FROM workspaces WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        if not ws:
            raise DomainError(404, "workspace_not_found", "Workspace tidak ditemukan.")

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
        caller_workspace_id: str | None,
        actor_status: str | None = None,
    ) -> list[dict[str, Any]]:
        with db_transaction(self.db_path) as conn:
            self._assert_workspace_access(conn, workspace_id, caller_workspace_id, actor_status)
            rows = conn.execute(
                "SELECT * FROM offerings WHERE workspace_id = ? ORDER BY created_at ASC",
                (workspace_id,),
            ).fetchall()
            return [_row_to_offering(r) for r in rows]

    def get_offering(
        self,
        workspace_id: str,
        offering_id: str,
        caller_workspace_id: str | None,
        actor_status: str | None = None,
    ) -> dict[str, Any]:
        with db_transaction(self.db_path) as conn:
            self._assert_workspace_access(conn, workspace_id, caller_workspace_id, actor_status)
            row = conn.execute(
                "SELECT * FROM offerings WHERE workspace_id = ? AND offering_id = ?",
                (workspace_id, offering_id),
            ).fetchone()
            if not row:
                raise DomainError(404, "offering_not_found", "Offering tidak ditemukan pada workspace ini.")
            return _row_to_offering(row)

    def create_offering(
        self,
        workspace_id: str,
        caller_workspace_id: str | None,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        actor: str = "synthetic_owner",
        actor_status: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        with db_transaction(self.db_path, immediate=True) as conn:
            self._assert_workspace_access(conn, workspace_id, caller_workspace_id, actor_status)
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
                "tax_status": validated.tax_status,
                "tax_reason": validated.tax_reason,
                "tax_amount": None,
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
        caller_workspace_id: str | None,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        actor: str = "synthetic_owner",
        actor_status: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        with db_transaction(self.db_path, immediate=True) as conn:
            self._assert_workspace_access(conn, workspace_id, caller_workspace_id, actor_status)
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

            occurred_at = _normalize_occurred_at(validated.occurred_at)
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
        caller_workspace_id: str | None,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        actor: str = "synthetic_owner",
        actor_status: str | None = None,
        fault_injector: Callable[[Any], None] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        with db_transaction(self.db_path, immediate=True) as conn:
            self._assert_workspace_access(conn, workspace_id, caller_workspace_id, actor_status)
            validated = validate_sale_input(payload)
            req_hash = _hash_payload(payload)

            replay = self._check_idempotency(conn, workspace_id, "create_sale", idempotency_key, req_hash)
            if replay:
                return replay

            occurred_at = _normalize_occurred_at(validated.occurred_at)
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
                total_revenue_idr += revenue_idr

                line_cogs_idr: int | None = None
                line_cost_status = "open"

                if off["requires_stock_movement"]:
                    batches = conn.execute(
                        """
                        SELECT batch_id, qty_initial, qty_remaining, total_cost_idr
                        FROM inventory_batches
                        WHERE workspace_id = ? AND offering_id = ? AND CAST(qty_remaining AS REAL) > 0
                        ORDER BY occurred_at ASC, batch_id ASC
                        """,
                        (workspace_id, line.offering_id),
                    ).fetchall()

                    total_qty_avail = sum((Decimal(b["qty_remaining"]) for b in batches), Decimal("0"))
                    if total_qty_avail < line.qty:
                        raise DomainError(
                            409,
                            "insufficient_stock",
                            f"Stok tidak mencukupi untuk {off['name']} (tersedia {total_qty_avail}, diminta {line.qty}).",
                        )

                    # Weighted Average (WA) unit cost across remaining inventory batches
                    total_val_avail = Decimal("0")
                    for b in batches:
                        b_init = Decimal(b["qty_initial"])
                        b_rem = Decimal(b["qty_remaining"])
                        b_val = (Decimal(b["total_cost_idr"]) * b_rem) / b_init
                        total_val_avail += b_val

                    wa_unit_cost = total_val_avail / total_qty_avail
                    line_cogs_idr = round_idr(line.qty * wa_unit_cost)
                    line_cost_status = "assessed"
                    if total_cogs_idr is not None:
                        total_cogs_idr += line_cogs_idr

                    # Deduct qty_remaining across batches proportionally/FIFO-wise while keeping total WA value consistent
                    remaining_to_deduct = line.qty
                    for b in batches:
                        if remaining_to_deduct <= 0:
                            break
                        b_rem = Decimal(b["qty_remaining"])
                        take = min(b_rem, remaining_to_deduct)
                        new_rem = b_rem - take
                        conn.execute(
                            "UPDATE inventory_batches SET qty_remaining = ? WHERE batch_id = ?",
                            (str(new_rem), b["batch_id"]),
                        )
                        remaining_to_deduct -= take

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

            if fault_injector is not None:
                fault_injector(conn)

            return 201, result

    def get_daily_report(
        self,
        workspace_id: str,
        caller_workspace_id: str | None,
        date_str: str | None = None,
        actor_status: str | None = None,
    ) -> dict[str, Any]:
        with db_transaction(self.db_path) as conn:
            self._assert_workspace_access(conn, workspace_id, caller_workspace_id, actor_status)

            if date_str:
                try:
                    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError as exc:
                    raise DomainError(422, "invalid_date", "Format tanggal harus YYYY-MM-DD.") from exc
            else:
                target_date = datetime.now(JAKARTA_TZ).date()

            start_local = datetime(target_date.year, target_date.month, target_date.day, tzinfo=JAKARTA_TZ)
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

            # Ending inventory snapshot (WA value = total purchase cost - total assessed sale COGS)
            batch_rows = conn.execute(
                """
                SELECT b.offering_id, o.name, o.unit, b.qty_remaining, b.total_cost_idr
                FROM inventory_batches b
                JOIN offerings o ON o.offering_id = b.offering_id
                WHERE b.workspace_id = ? AND b.occurred_at < ?
                """,
                (workspace_id, end_utc),
            ).fetchall()

            cogs_by_off_rows = conn.execute(
                """
                SELECT sl.offering_id, COALESCE(SUM(sl.cogs_idr), 0) AS total_cogs
                FROM sale_lines sl
                JOIN sales s ON s.sale_id = sl.sale_id
                WHERE sl.workspace_id = ? AND s.occurred_at < ? AND sl.cost_status = 'assessed'
                GROUP BY sl.offering_id
                """,
                (workspace_id, end_utc),
            ).fetchall()
            cogs_by_off = {r["offering_id"]: int(r["total_cogs"]) for r in cogs_by_off_rows}

            inv_by_off: dict[str, dict[str, Any]] = {}
            for b in batch_rows:
                oid = b["offering_id"]
                if oid not in inv_by_off:
                    inv_by_off[oid] = {
                        "offering_id": oid,
                        "name": b["name"],
                        "unit": b["unit"],
                        "qty": Decimal("0"),
                        "total_cost_in": 0,
                    }
                inv_by_off[oid]["qty"] += Decimal(b["qty_remaining"])
                inv_by_off[oid]["total_cost_in"] += int(b["total_cost_idr"])

            inv_items = []
            total_inv_qty = Decimal("0")
            total_inv_value_idr = 0
            for oid, item in inv_by_off.items():
                val_idr = item["total_cost_in"] - cogs_by_off.get(oid, 0)
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
                SELECT * FROM purchases
                WHERE workspace_id = ? AND occurred_at >= ? AND occurred_at < ?
                ORDER BY occurred_at ASC
                """,
                (workspace_id, start_utc, end_utc),
            ).fetchall()
            movement_rows = conn.execute(
                """
                SELECT * FROM stock_movements
                WHERE workspace_id = ? AND occurred_at >= ? AND occurred_at < ?
                ORDER BY occurred_at ASC
                """,
                (workspace_id, start_utc, end_utc),
            ).fetchall()
            audit_rows = conn.execute(
                """
                SELECT * FROM audit_events
                WHERE workspace_id = ?
                ORDER BY created_at DESC LIMIT 50
                """,
                (workspace_id,),
            ).fetchall()

            return {
                "workspace_id": workspace_id,
                "period": {
                    "date": target_date.isoformat(),
                    "timezone": "Asia/Jakarta",
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
                    "sales": [dict(r) for r in sales_rows],
                    "stock_movements": [dict(r) for r in movement_rows],
                    "cash_movements": [dict(r) for r in cash_rows],
                    "audit_events": [dict(r) for r in audit_rows],
                },
            }
