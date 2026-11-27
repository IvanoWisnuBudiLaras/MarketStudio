"""Application service layer: tenant isolation, idempotency, and audit."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.db import DEFAULT_DB_PATH, db_transaction
from app.domain import (
    DomainError,
    validate_offering_input,
    validate_workspace_input,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    """Modular monolith service for Workspaces and Offerings."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path

    def list_workspaces(self) -> list[dict[str, Any]]:
        with db_transaction(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM workspaces ORDER BY created_at ASC"
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

        with db_transaction(self.db_path) as conn:
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
        self, conn: Any, workspace_id: str, caller_workspace_id: str | None
    ) -> None:
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

    def list_offerings(
        self, workspace_id: str, caller_workspace_id: str | None
    ) -> list[dict[str, Any]]:
        with db_transaction(self.db_path) as conn:
            self._assert_workspace_access(conn, workspace_id, caller_workspace_id)
            rows = conn.execute(
                "SELECT * FROM offerings WHERE workspace_id = ? ORDER BY created_at ASC",
                (workspace_id,),
            ).fetchall()
            return [_row_to_offering(r) for r in rows]

    def get_offering(
        self, workspace_id: str, offering_id: str, caller_workspace_id: str | None
    ) -> dict[str, Any]:
        with db_transaction(self.db_path) as conn:
            self._assert_workspace_access(conn, workspace_id, caller_workspace_id)
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
    ) -> tuple[int, dict[str, Any]]:
        with db_transaction(self.db_path) as conn:
            self._assert_workspace_access(conn, workspace_id, caller_workspace_id)
            validated = validate_offering_input(payload)
            req_hash = _hash_payload(payload)

            if idempotency_key:
                existing = conn.execute(
                    """
                    SELECT request_hash, status_code, response_body
                    FROM idempotency_keys
                    WHERE workspace_id = ? AND operation = ? AND idempotency_key = ?
                    """,
                    (workspace_id, "create_offering", idempotency_key),
                ).fetchone()
                if existing:
                    if existing["request_hash"] != req_hash:
                        raise DomainError(
                            409,
                            "idempotency_conflict",
                            "Idempotency-Key sudah dipakai dengan payload berbeda.",
                        )
                    return existing["status_code"], json.loads(existing["response_body"])

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

            if idempotency_key:
                conn.execute(
                    """
                    INSERT INTO idempotency_keys (
                        workspace_id, operation, idempotency_key, request_hash, status_code, response_body, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (workspace_id, "create_offering", idempotency_key, req_hash, 201, json.dumps(result), created_at),
                )
            return 201, result
