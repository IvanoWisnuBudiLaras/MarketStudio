"""Domain models, validation, and error types for MarketStudio baseline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from urllib.parse import urlparse
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


MAX_DERIVED_IDR = 10**15


def round_idr(value: Decimal) -> int:
    """Round a Decimal Rupiah value half-up to integer."""
    if not value.is_finite() or abs(value) > Decimal(MAX_DERIVED_IDR):
        raise DomainError(
            422,
            "value_overflow",
            f"Nilai turunan melebihi batas maksimum {MAX_DERIVED_IDR:,} IDR.",
            {"total_idr": f"Nilai turunan melebihi batas maksimum {MAX_DERIVED_IDR:,} IDR."},
        )
    try:
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, OverflowError) as exc:
        raise DomainError(
            422,
            "value_overflow",
            f"Nilai turunan melebihi batas maksimum {MAX_DERIVED_IDR:,} IDR.",
            {"total_idr": f"Nilai turunan melebihi batas maksimum {MAX_DERIVED_IDR:,} IDR."},
        ) from exc


def ensure_idr_bound(value: int, field: str = "total_idr") -> int:
    """Guard against 64-bit SQLite integer overflow on derived IDR totals."""
    if abs(value) > MAX_DERIVED_IDR:
        raise DomainError(
            422,
            "value_overflow",
            f"{field} melebihi batas maksimum {MAX_DERIVED_IDR:,} IDR.",
            {field: f"Nilai turunan melebihi batas maksimum {MAX_DERIVED_IDR:,} IDR."},
        )
    return value


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
    description: str = ""


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

    description = payload.get("description", "")
    if not isinstance(description, str) or len(description.strip()) > 240:
        errors["description"] = "Deskripsi harus berupa teks hingga 240 karakter."

    raw_price = payload.get("unit_price_idr")
    if isinstance(raw_price, bool) or not isinstance(raw_price, int) or raw_price < 0 or raw_price > 10**15:
        errors["unit_price_idr"] = "Harga satuan (IDR) harus bilangan bulat 0..10^15."

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
    if offering_type == "service" and raw_val_method is not None:
        errors["valuation_method"] = "Offering tipe 'service' tidak boleh memiliki valuation_method."
    elif raw_val_method is not None and raw_val_method != "WA":
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
        description=description.strip(),
    )


def validate_purchase_input(payload: dict[str, Any]) -> PurchaseInput:
    """Validate cash purchase payload."""
    errors: dict[str, str] = {}
    offering_id = payload.get("offering_id")
    if not isinstance(offering_id, str) or not offering_id.strip():
        errors["offering_id"] = "offering_id wajib diisi."

    qty = parse_positive_decimal(payload.get("qty"), "qty", errors)

    total_cost_idr = payload.get("total_cost_idr")
    if isinstance(total_cost_idr, bool) or not isinstance(total_cost_idr, int) or total_cost_idr < 0 or total_cost_idr > 10**15:
        errors["total_cost_idr"] = "total_cost_idr harus bilangan bulat 0..10^15."

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
            isinstance(total_price, bool) or not isinstance(total_price, int) or total_price < 0 or total_price > 10**15
        ):
            errors[f"lines[{idx}].total_price_idr"] = "total_price_idr harus bilangan bulat 0..10^15."
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


@dataclass(frozen=True)
class SimulationInput:
    offering_id: str | None
    unit_cost_idr: int | None
    selling_price_idr: int | None
    discount_percent: Decimal


def _parse_non_negative_idr(value: Any, field: str, errors: dict[str, str]) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > MAX_DERIVED_IDR:
        errors[field] = f"{field} harus bilangan bulat 0..{MAX_DERIVED_IDR:,}."
        return None
    return value


def _parse_discount_percent(value: Any, errors: dict[str, str]) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, bool):
        errors["discount_percent"] = "discount_percent tidak boleh boolean."
        return Decimal("0")
    try:
        dec = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        errors["discount_percent"] = "discount_percent harus berupa angka desimal yang valid."
        return Decimal("0")
    if not dec.is_finite() or dec < 0 or dec > Decimal("100"):
        errors["discount_percent"] = "discount_percent harus di antara 0 dan 100."
        return Decimal("0")
    return dec


def validate_simulation_input(payload: dict[str, Any]) -> SimulationInput:
    """Validate price & discount simulation payload."""
    errors: dict[str, str] = {}
    raw_offering_id = payload.get("offering_id")
    offering_id: str | None = None
    if raw_offering_id is not None:
        if not isinstance(raw_offering_id, str) or not raw_offering_id.strip():
            errors["offering_id"] = "offering_id harus berupa string non-kosong."
        else:
            offering_id = raw_offering_id.strip()

    unit_cost_idr: int | None = None
    if payload.get("unit_cost_idr") is not None:
        unit_cost_idr = _parse_non_negative_idr(payload.get("unit_cost_idr"), "unit_cost_idr", errors)

    raw_price = payload.get("simulated_price_idr")
    price_field = "simulated_price_idr"
    if raw_price is None and "selling_price_idr" in payload:
        raw_price = payload.get("selling_price_idr")
        price_field = "selling_price_idr"

    selling_price_idr: int | None = None
    if raw_price is not None:
        selling_price_idr = _parse_non_negative_idr(raw_price, price_field, errors)
    elif offering_id is None:
        errors["selling_price_idr"] = "selling_price_idr atau simulated_price_idr wajib diisi jika tanpa offering_id."

    discount_percent = _parse_discount_percent(payload.get("discount_percent"), errors)

    if errors:
        raise DomainError(422, "validation_error", "Data simulasi tidak valid.", errors)
    return SimulationInput(
        offering_id=offering_id,
        unit_cost_idr=unit_cost_idr,
        selling_price_idr=selling_price_idr,
        discount_percent=discount_percent,
    )


def _format_pct(value: Decimal) -> str:
    q = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if q == 0:
        return "0"
    return format(q.normalize(), "f")


def compute_price_simulation(
    *,
    selling_price_idr: int,
    discount_percent: Decimal,
    unit_cost_idr: int | None,
) -> dict[str, Any]:
    """Deterministically compute net price, gross delta, margin, and markup without mutating state."""
    ensure_idr_bound(selling_price_idr, "selling_price_idr")
    net_price_idr = round_idr(
        Decimal(selling_price_idr) * (Decimal("100") - discount_percent) / Decimal("100")
    )
    ensure_idr_bound(net_price_idr, "net_price_idr")

    if unit_cost_idr is None:
        return {
            "selling_price_idr": selling_price_idr,
            "discount_percent": _format_pct(discount_percent),
            "net_price_idr": net_price_idr,
            "unit_cost_idr": None,
            "cost_status": "open",
            "gross_delta_idr": None,
            "margin_percent": None,
            "markup_percent": None,
            "margin_status": "unavailable",
        }

    ensure_idr_bound(unit_cost_idr, "unit_cost_idr")
    gross_delta_idr = net_price_idr - unit_cost_idr
    ensure_idr_bound(gross_delta_idr, "gross_delta_idr")

    if net_price_idr == 0:
        margin_status = "unavailable"
        margin_percent: str | None = None
    else:
        margin_status = "assessed"
        margin_percent = _format_pct(Decimal(gross_delta_idr) * Decimal("100") / Decimal(net_price_idr))

    markup_percent: str | None = None
    if unit_cost_idr > 0:
        markup_percent = _format_pct(Decimal(gross_delta_idr) * Decimal("100") / Decimal(unit_cost_idr))

    return {
        "selling_price_idr": selling_price_idr,
        "discount_percent": _format_pct(discount_percent),
        "net_price_idr": net_price_idr,
        "unit_cost_idr": unit_cost_idr,
        "cost_status": "assessed",
        "gross_delta_idr": gross_delta_idr,
        "margin_percent": margin_percent,
        "markup_percent": markup_percent,
        "margin_status": margin_status,
    }


BENCHMARK_SNAPSHOTS: tuple[dict[str, Any], ...] = (
    {
        "snapshot_id": "bapanas_beras_medium_maret_2026",
        "source_kind": "transcribed_official",
        "is_synthetic": False,
        "is_historical": True,
        "source_name": "Badan Pangan Nasional (Bapanas) — Publikasi Resmi",
        "source_url": "https://data.badanpangan.go.id/nfs_storage/public/publication/documents/1779588677.pdf",
        "observed_at": "2026-03",
        "observation_period": "Maret 2026",
        "location_market": "Nasional (Tingkat Konsumen)",
        "commodity_name": "Beras Medium",
        "unit": "kg",
        "quantity": "1",
        "currency": "IDR",
        "observed_price_idr": 13378,
        "evidence_note": "Transkripsi resmi Bapanas: Tabel Harga Pangan Tingkat Konsumen Periode Maret 2026, halaman cetak 20, baris Beras Medium, kolom Harga Nasional (data historis, bukan harga spot saat ini).",
    },
    {
        "snapshot_id": "demo_beras_medium_jkt",
        "source_kind": "synthetic_demo",
        "is_synthetic": True,
        "source_name": "Demo Sintetis MarketStudio (Beras Medium)",
        "source_url": None,
        "observed_at": "2026-11-26T00:00:00+07:00",
        "location_market": "Pasar Induk Kramat Jati, DKI Jakarta (Sintetis)",
        "commodity_name": "Beras Medium (Demo Sintetis)",
        "unit": "kg",
        "quantity": "1",
        "currency": "IDR",
        "observed_price_idr": 13500,
        "evidence_note": "Demo sintetis — bukan observasi pasar nyata. Gunakan manual_fallback dengan bukti survei aktual untuk keputusan harga.",
    },
    {
        "snapshot_id": "demo_gula_pasir_500g_jkt",
        "source_kind": "synthetic_demo",
        "is_synthetic": True,
        "source_name": "Demo Sintetis MarketStudio (Gula Konsumsi 500 g)",
        "source_url": None,
        "observed_at": "2026-11-26T00:00:00+07:00",
        "location_market": "Pasar Senen, DKI Jakarta (Sintetis)",
        "commodity_name": "Gula Konsumsi 500 g (Demo Sintetis)",
        "unit": "g",
        "quantity": "500",
        "currency": "IDR",
        "observed_price_idr": 9000,
        "evidence_note": "Demo sintetis — bukan observasi pasar nyata. Gunakan manual_fallback dengan bukti survei aktual untuk keputusan harga.",
    },
    {
        "snapshot_id": "demo_minyak_goreng_jkt",
        "source_kind": "synthetic_demo",
        "is_synthetic": True,
        "source_name": "Demo Sintetis MarketStudio (Minyak Goreng)",
        "source_url": None,
        "observed_at": "2026-11-26T00:00:00+07:00",
        "location_market": "Pasar Minggu, DKI Jakarta (Sintetis)",
        "commodity_name": "Minyak Goreng Kemasan Sederhana (Demo Sintetis)",
        "unit": "liter",
        "quantity": "1",
        "currency": "IDR",
        "observed_price_idr": 17500,
        "evidence_note": "Demo sintetis — bukan observasi pasar nyata. Gunakan manual_fallback dengan bukti survei aktual untuk keputusan harga.",
    },
)

_BENCHMARK_SNAPSHOT_MAP: dict[str, dict[str, Any]] = {
    item["snapshot_id"]: item for item in BENCHMARK_SNAPSHOTS
}

_UNIT_CONVERSIONS: dict[tuple[str, str], Decimal] = {
    ("kg", "g"): Decimal("1000"),
    ("g", "kg"): Decimal("0.001"),
    ("liter", "ml"): Decimal("1000"),
    ("ml", "liter"): Decimal("0.001"),
}


@dataclass(frozen=True)
class BenchmarkObservation:
    source_kind: str
    source_name: str
    source_url: str | None
    observed_at: str
    location_market: str
    unit: str
    quantity: Decimal
    currency: str
    observed_price_idr: int
    snapshot_id: str | None = None
    commodity_name: str | None = None
    evidence_note: str | None = None
    is_historical: bool = False
    observation_period: str | None = None


def _validate_iso_observed_at(raw: Any, errors: dict[str, str]) -> str:
    if not isinstance(raw, str) or not raw.strip():
        errors["observed_at"] = "observed_at wajib diisi (ISO date/timestamp)."
        return ""
    val = raw.strip()
    try:
        if len(val) == 10:
            datetime.strptime(val, "%Y-%m-%d")
        else:
            datetime.fromisoformat(val.replace("Z", "+00:00"))
    except ValueError:
        errors["observed_at"] = "observed_at harus berupa tanggal/timestamp ISO yang valid."
        return ""
    return val


def validate_benchmark_input(payload: dict[str, Any]) -> tuple[str, BenchmarkObservation]:
    """Validate price benchmark comparison payload (attributed_snapshot or manual_fallback)."""
    errors: dict[str, str] = {}
    raw_offering_id = payload.get("offering_id")
    if not isinstance(raw_offering_id, str) or not raw_offering_id.strip():
        errors["offering_id"] = "offering_id wajib diisi."
        offering_id = ""
    else:
        offering_id = raw_offering_id.strip()

    raw_kind = payload.get("source_kind")
    if raw_kind not in ("transcribed_official", "synthetic_demo", "manual_fallback"):
        errors["source_kind"] = "source_kind harus 'transcribed_official', 'synthetic_demo', atau 'manual_fallback'."
        raise DomainError(422, "validation_error", "Data benchmark tidak valid.", errors)

    if raw_kind in ("transcribed_official", "synthetic_demo"):
        snap_id = payload.get("snapshot_id")
        if not isinstance(snap_id, str) or not snap_id.strip():
            errors["snapshot_id"] = f"snapshot_id wajib diisi untuk {raw_kind}."
        elif snap_id.strip() not in _BENCHMARK_SNAPSHOT_MAP:
            errors["snapshot_id"] = f"Snapshot '{snap_id}' tidak ditemukan."
        elif _BENCHMARK_SNAPSHOT_MAP[snap_id.strip()]["source_kind"] != raw_kind:
            errors["snapshot_id"] = f"Snapshot '{snap_id}' bukan bertipe {raw_kind}."
        if errors:
            raise DomainError(422, "validation_error", "Data benchmark tidak valid.", errors)
        snap = _BENCHMARK_SNAPSHOT_MAP[snap_id.strip()]
        return offering_id, BenchmarkObservation(
            source_kind=snap["source_kind"],
            source_name=snap["source_name"],
            source_url=snap["source_url"],
            observed_at=snap["observed_at"],
            location_market=snap["location_market"],
            unit=snap["unit"],
            quantity=Decimal(snap["quantity"]),
            currency=snap["currency"],
            observed_price_idr=int(snap["observed_price_idr"]),
            snapshot_id=snap["snapshot_id"],
            commodity_name=snap["commodity_name"],
            evidence_note=snap["evidence_note"],
            is_historical=bool(snap.get("is_historical", False)),
            observation_period=snap.get("observation_period"),
        )

    # manual_fallback
    source_label = payload.get("source_label")
    if not isinstance(source_label, str) or not source_label.strip():
        errors["source_label"] = "source_label wajib diisi untuk manual_fallback."
    evidence_note = payload.get("evidence_note")
    if not isinstance(evidence_note, str) or not evidence_note.strip():
        errors["evidence_note"] = "evidence_note wajib diisi untuk manual_fallback."
    location_market = payload.get("location_market")
    if not isinstance(location_market, str) or not location_market.strip():
        errors["location_market"] = "location_market wajib diisi."
    unit = payload.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        errors["unit"] = "unit wajib diisi."

    observed_at = _validate_iso_observed_at(payload.get("observed_at"), errors)
    quantity = parse_positive_decimal(payload.get("quantity"), "quantity", errors)
    observed_price_idr = _parse_non_negative_idr(payload.get("observed_price_idr"), "observed_price_idr", errors)

    currency = payload.get("currency")
    if not isinstance(currency, str) or currency.strip().upper() != "IDR":
        errors["currency"] = "currency wajib 'IDR'."

    source_url_raw = payload.get("source_url")
    source_url: str | None = None
    if source_url_raw is not None:
        if not isinstance(source_url_raw, str):
            errors["source_url"] = "source_url harus berupa string."
        elif source_url_raw.strip():
            candidate_url = source_url_raw.strip()
            parsed_url = urlparse(candidate_url)
            if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
                errors["source_url"] = "source_url harus berupa URL http:// atau https:// yang valid."
            else:
                source_url = candidate_url

    if errors:
        raise DomainError(422, "validation_error", "Data benchmark manual tidak valid.", errors)

    assert quantity is not None and observed_price_idr is not None
    return offering_id, BenchmarkObservation(
        source_kind="manual_fallback",
        source_name=source_label.strip(),
        source_url=source_url,
        observed_at=observed_at,
        location_market=location_market.strip(),
        unit=unit.strip().lower(),
        quantity=quantity,
        currency="IDR",
        observed_price_idr=observed_price_idr,
        snapshot_id=None,
        commodity_name=None,
        evidence_note=evidence_note.strip(),
    )


def compute_price_benchmark(
    *,
    offering_unit: str,
    offering_unit_price_idr: int,
    observation: BenchmarkObservation,
) -> dict[str, Any]:
    """Deterministically compare offering unit price against a benchmark observation."""
    off_unit = offering_unit.strip().lower()
    obs_unit = observation.unit.strip().lower()

    if off_unit == obs_unit:
        factor = Decimal("1")
    elif (off_unit, obs_unit) in _UNIT_CONVERSIONS:
        factor = _UNIT_CONVERSIONS[(off_unit, obs_unit)]
    else:
        raise DomainError(
            422,
            "incomparable_units",
            f"Satuan offering '{off_unit}' tidak dapat dibandingkan dengan satuan benchmark '{obs_unit}'.",
            {"offering_unit": off_unit, "observation_unit": obs_unit},
        )

    ensure_idr_bound(offering_unit_price_idr, "offering_unit_price_idr")
    ensure_idr_bound(observation.observed_price_idr, "observed_price_idr")

    normalized_benchmark_price_idr = round_idr(
        (Decimal(observation.observed_price_idr) / observation.quantity) * factor
    )
    ensure_idr_bound(normalized_benchmark_price_idr, "normalized_benchmark_price_idr")

    price_delta_idr = offering_unit_price_idr - normalized_benchmark_price_idr
    ensure_idr_bound(price_delta_idr, "price_delta_idr")

    price_delta_percent: str | None = None
    if normalized_benchmark_price_idr > 0:
        price_delta_percent = _format_pct(
            Decimal(price_delta_idr) * Decimal("100") / Decimal(normalized_benchmark_price_idr)
        )

    return {
        "comparable": True,
        "offering_unit": off_unit,
        "offering_unit_price_idr": offering_unit_price_idr,
        "normalized_benchmark_price_idr": normalized_benchmark_price_idr,
        "price_delta_idr": price_delta_idr,
        "price_delta_percent": price_delta_percent,
        "observation": {
            "snapshot_id": observation.snapshot_id,
            "commodity_name": observation.commodity_name,
            "source_kind": observation.source_kind,
            "is_synthetic": observation.source_kind == "synthetic_demo",
            "is_historical": observation.is_historical,
            "observation_period": observation.observation_period,
            "source_name": observation.source_name,
            "source_url": observation.source_url,
            "observed_at": observation.observed_at,
            "location_market": observation.location_market,
            "unit": obs_unit,
            "quantity": format(observation.quantity.normalize(), "f"),
            "currency": observation.currency,
            "observed_price_idr": observation.observed_price_idr,
            "evidence_note": observation.evidence_note,
        },
    }
