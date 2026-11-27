"""Domain models, validation, and error types for MarketStudio baseline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from zoneinfo import available_timezones

VALID_OFFERING_TYPES = ("goods", "service", "hybrid")
VALID_TAX_STATUSES = ("not_assessed", "unknown")
DEFAULT_TAX_REASON = "Pajak belum dinilai pada baseline sintetis (tidak diasumsikan 0)."
POLICY_VERSION = "v1-wa-not-assessed"
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


def parse_positive_decimal(value: Any, field: str, errors: dict[str, str]) -> Decimal | None:
    """Parse a positive Decimal from string/int/float without binary float drift."""
    if isinstance(value, bool) or value is None:
        errors[field] = f"{field} wajib diisi dan harus > 0."
        return None
    try:
        dec = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        errors[field] = f"{field} harus berupa angka desimal yang valid."
        return None
    if not dec.is_finite() or dec <= 0 or dec > Decimal("1000000000"):
        errors[field] = f"{field} harus > 0, <= 1.000.000.000, dan bukan NaN/Infinity."
        return None
    return dec


def round_idr(value: Decimal) -> int:
    """Round a Decimal Rupiah value half-up to integer."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


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


@dataclass(frozen=True)
class PurchaseInput:
    offering_id: str
    qty: Decimal
    total_cost_idr: int
    occurred_at: str | None = None


@dataclass(frozen=True)
class SaleLineInput:
    offering_id: str
    qty: Decimal
    total_price_idr: int | None = None


@dataclass(frozen=True)
class SaleInput:
    lines: list[SaleLineInput]
    occurred_at: str | None = None


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
    timezone = raw_tz.strip() if isinstance(raw_tz, str) and raw_tz.strip() else ""
    if not timezone or timezone not in available_timezones():
        errors["timezone"] = "Timezone tidak valid (gunakan IANA timezone, contoh: Asia/Jakarta)."

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

    if "requires_stock_movement" in payload and payload["requires_stock_movement"] is not None:
        if not isinstance(payload["requires_stock_movement"], bool):
            errors["requires_stock_movement"] = "requires_stock_movement harus berupa boolean (true/false)."
        elif offering_type == "service" and payload["requires_stock_movement"] is True:
            errors["requires_stock_movement"] = "Offering tipe 'service' tidak boleh memiliki requires_stock_movement=true."
        elif offering_type == "goods" and payload["requires_stock_movement"] is False:
            errors["requires_stock_movement"] = "Offering tipe 'goods' wajib memiliki requires_stock_movement=true."

    raw_val_method = payload.get("valuation_method")
    if raw_val_method is not None and raw_val_method != "WA":
        errors["valuation_method"] = "Metode valuasi terkunci pada 'WA' (Weighted Average) untuk baseline ini."

    if errors:
        raise DomainError(422, "validation_error", "Data produk/jasa tidak valid.", errors)

    if offering_type == "service":
        requires_stock = False
        valuation_method = None
    else:
        req = payload.get("requires_stock_movement")
        requires_stock = True if req is None else req
        valuation_method = "WA" if requires_stock else None

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


def validate_purchase_input(payload: dict[str, Any]) -> PurchaseInput:
    """Validate cash purchase payload."""
    errors: dict[str, str] = {}
    offering_id = payload.get("offering_id")
    if not isinstance(offering_id, str) or not offering_id.strip():
        errors["offering_id"] = "offering_id wajib diisi."

    qty = parse_positive_decimal(payload.get("qty"), "qty", errors)

    total_cost_idr = payload.get("total_cost_idr")
    if isinstance(total_cost_idr, bool) or not isinstance(total_cost_idr, int) or total_cost_idr < 0:
        errors["total_cost_idr"] = "total_cost_idr harus bilangan bulat >= 0."

    payment_method = payload.get("payment_method", "cash")
    if payment_method != "cash":
        errors["payment_method"] = "Hanya pembayaran tunai ('cash') yang didukung pada baseline ini."

    if errors or qty is None:
        raise DomainError(422, "validation_error", "Data pembelian tidak valid.", errors)

    return PurchaseInput(
        offering_id=offering_id.strip(),
        qty=qty,
        total_cost_idr=total_cost_idr,
        occurred_at=payload.get("occurred_at"),
    )


def validate_sale_input(payload: dict[str, Any]) -> SaleInput:
    """Validate sale payload with one or more lines."""
    errors: dict[str, str] = {}
    raw_lines = payload.get("lines")
    if not isinstance(raw_lines, list) or len(raw_lines) == 0:
        raise DomainError(
            422,
            "validation_error",
            "Data penjualan tidak valid.",
            {"lines": "Minimal 1 baris penjualan wajib diisi."},
        )

    lines: list[SaleLineInput] = []
    for idx, raw_line in enumerate(raw_lines):
        if not isinstance(raw_line, dict):
            errors[f"lines[{idx}]"] = "Baris penjualan harus berupa object."
            continue
        off_id = raw_line.get("offering_id")
        if not isinstance(off_id, str) or not off_id.strip():
            errors[f"lines[{idx}].offering_id"] = "offering_id wajib diisi."
        qty = parse_positive_decimal(raw_line.get("qty"), f"lines[{idx}].qty", errors)
        total_price = raw_line.get("total_price_idr")
        if total_price is not None and (
            isinstance(total_price, bool) or not isinstance(total_price, int) or total_price < 0
        ):
            errors[f"lines[{idx}].total_price_idr"] = "total_price_idr harus bilangan bulat >= 0."
        if qty is not None and isinstance(off_id, str) and off_id.strip():
            lines.append(
                SaleLineInput(
                    offering_id=off_id.strip(),
                    qty=qty,
                    total_price_idr=total_price,
                )
            )

    if errors:
        raise DomainError(422, "validation_error", "Data penjualan tidak valid.", errors)

    payment_method = payload.get("payment_method", "cash")
    if payment_method != "cash":
        raise DomainError(
            422,
            "validation_error",
            "Data penjualan tidak valid.",
            {"payment_method": "Hanya pembayaran tunai ('cash') yang didukung pada baseline ini."},
        )

    return SaleInput(lines=lines, occurred_at=payload.get("occurred_at"))
