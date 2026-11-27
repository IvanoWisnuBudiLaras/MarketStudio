"""Domain models, validation, and error types for MarketStudio baseline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

VALID_OFFERING_TYPES = ("goods", "service", "hybrid")
VALID_TAX_STATUSES = ("not_assessed", "unknown")
DEFAULT_TAX_REASON = "Pajak belum dinilai pada baseline sintetis (tidak diasumsikan 0)."
_NAME_PATTERN = re.compile(r"^[\w\s\-.,/+&()]+$", re.UNICODE)


class DomainError(Exception):
    """Base error mapped to structured HTTP error envelope."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        field_errors: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field_errors = field_errors or {}


@dataclass(frozen=True)
class WorkspaceInput:
    name: str
    business_type: str = "umkm_hybrid"
    timezone: str = "Asia/Jakarta"


@dataclass(frozen=True)
class OfferingInput:
    name: str
    offering_type: str
    unit_price_idr: int
    unit: str = "pcs"
    requires_stock_movement: bool | None = None
    valuation_method: str | None = None
    tax_status: str = "not_assessed"
    tax_reason: str = DEFAULT_TAX_REASON


def validate_workspace_input(payload: dict[str, Any]) -> WorkspaceInput:
    """Validate workspace creation payload."""
    errors: dict[str, str] = {}
    raw_name = payload.get("name")
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not name or len(name) < 2 or not _NAME_PATTERN.match(name):
        errors["name"] = "Nama workspace wajib diisi (minimal 2 karakter valid)."

    raw_type = payload.get("business_type", "umkm_hybrid")
    business_type = raw_type.strip() if isinstance(raw_type, str) and raw_type.strip() else "umkm_hybrid"

    raw_tz = payload.get("timezone", "Asia/Jakarta")
    timezone = raw_tz.strip() if isinstance(raw_tz, str) and raw_tz.strip() else "Asia/Jakarta"

    if errors:
        raise DomainError(422, "validation_error", "Data workspace tidak valid.", errors)

    return WorkspaceInput(name=name, business_type=business_type, timezone=timezone)


def validate_offering_input(payload: dict[str, Any]) -> OfferingInput:
    """Validate offering creation payload with goods/service/hybrid and tax invariants."""
    errors: dict[str, str] = {}

    raw_name = payload.get("name")
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not name or len(name) < 2 or not _NAME_PATTERN.match(name):
        errors["name"] = "Nama produk/jasa wajib diisi (minimal 2 karakter valid)."

    offering_type = payload.get("offering_type")
    if offering_type not in VALID_OFFERING_TYPES:
        errors["offering_type"] = f"Tipe harus salah satu dari: {', '.join(VALID_OFFERING_TYPES)}."

    raw_price = payload.get("unit_price_idr")
    if isinstance(raw_price, bool) or not isinstance(raw_price, int) or raw_price < 0:
        errors["unit_price_idr"] = "Harga satuan (IDR) harus bilangan bulat >= 0."

    raw_unit = payload.get("unit", "pcs")
    unit = raw_unit.strip() if isinstance(raw_unit, str) and raw_unit.strip() else ""
    if not unit:
        errors["unit"] = "Satuan tidak boleh kosong."

    tax_status = payload.get("tax_status", "not_assessed")
    if tax_status not in VALID_TAX_STATUSES:
        errors["tax_status"] = f"Status pajak harus salah satu dari: {', '.join(VALID_TAX_STATUSES)}."

    raw_reason = payload.get("tax_reason", DEFAULT_TAX_REASON)
    tax_reason = raw_reason.strip() if isinstance(raw_reason, str) and raw_reason.strip() else ""
    if not tax_reason:
        errors["tax_reason"] = "Alasan status pajak wajib diisi."

    if "tax_amount" in payload and payload["tax_amount"] is not None:
        errors["tax_amount"] = "tax_amount tidak boleh diisi pada baseline (pajak belum dinilai)."

    if errors:
        raise DomainError(422, "validation_error", "Data produk/jasa tidak valid.", errors)

    # Services never require stock movement; goods/hybrid default to True unless specified.
    if offering_type == "service":
        requires_stock = False
        valuation_method = None
    else:
        req = payload.get("requires_stock_movement")
        requires_stock = True if req is None else bool(req)
        valuation_method = payload.get("valuation_method") or ("WA" if requires_stock else None)

    return OfferingInput(
        name=name,
        offering_type=offering_type,
        unit_price_idr=raw_price,
        unit=unit,
        requires_stock_movement=requires_stock,
        valuation_method=valuation_method,
        tax_status=tax_status,
        tax_reason=tax_reason,
    )
