"""AI Business Review adapter, anonymized snapshot builder, and deterministic fallback (#14/#40/#41)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from typing import Any

STUB_MODES = frozenset(
    {
        "stub_valid",
        "stub_timeout",
        "stub_error",
        "stub_empty",
        "stub_fake_citation",
        "stub_wrong_period",
    }
)

_REQUIRED_ENV_VARS = (
    "MARKETSTUDIO_AI_PROVIDER",
    "MARKETSTUDIO_AI_MODEL",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
)


def get_ai_provider_config_status() -> dict[str, Any]:
    """Check AI provider env configuration presence without ever reading or exposing secret values."""
    env_values = {key: (os.environ.get(key) or "").strip() for key in _REQUIRED_ENV_VARS}
    env_presence = {key: bool(val) for key, val in env_values.items()}
    provider = env_values["MARKETSTUDIO_AI_PROVIDER"] or None
    model = env_values["MARKETSTUDIO_AI_MODEL"] or None
    has_key = env_presence["GEMINI_API_KEY"] or env_presence["GOOGLE_API_KEY"]

    missing_env_vars: list[str] = []
    if not provider:
        missing_env_vars.append("MARKETSTUDIO_AI_PROVIDER")
    if not model:
        missing_env_vars.append("MARKETSTUDIO_AI_MODEL")
    if not has_key:
        missing_env_vars.append("GEMINI_API_KEY")

    unsupported_provider = bool(provider and provider != "gemini")
    configured = bool(provider == "gemini" and model and has_key)
    return {
        "configured": configured,
        "provider": provider,
        "model": model,
        "unsupported_provider": unsupported_provider,
        "env_presence": env_presence,
        "missing_env_vars": missing_env_vars,
        "setup_action": (
            f"Provider '{provider}' tidak didukung; gunakan MARKETSTUDIO_AI_PROVIDER=gemini."
            if unsupported_provider
            else (
                "Set MARKETSTUDIO_AI_PROVIDER=gemini, MARKETSTUDIO_AI_MODEL=gemini-2.5-flash, "
                "dan GEMINI_API_KEY di environment runtime."
            )
        ),
        "live_integration_verified": False,
    }


def build_metric_snapshot(report: dict[str, Any]) -> dict[str, Any]:
    """Build an authoritative server-side MetricSnapshot and anonymized outbound payload."""
    period = report["period"]
    snapshot_id = f"snap_{period['date']}_{uuid.uuid4().hex[:8]}"

    drill_down = report.get("drill_down", {})
    sale_ids = [s["sale_id"] for s in drill_down.get("sales", []) if "sale_id" in s]
    purchase_ids = [p["purchase_id"] for p in drill_down.get("purchases", []) if "purchase_id" in p]
    cash_ids = [
        str(c.get("cash_movement_id") or c.get("cash_id") or c.get("movement_id"))
        for c in drill_down.get("cash_movements", [])
        if c.get("cash_movement_id") or c.get("cash_id") or c.get("movement_id")
    ]
    movement_ids = [
        str(m.get("movement_id") or m.get("stock_movement_id"))
        for m in drill_down.get("stock_movements", [])
        if m.get("movement_id") or m.get("stock_movement_id")
    ]
    source_ids_all = sorted(set(sale_ids + purchase_ids + cash_ids + movement_ids))

    metrics = {
        "revenue_idr": report["revenue_idr"],
        "cogs_idr": report["cogs_idr"],
        "cogs_status": report["cogs_status"],
        "gross_profit_idr": report["gross_profit_idr"],
        "gross_profit_status": report["gross_profit_status"],
        "cash_in_idr": report["cash_in_idr"],
        "cash_out_idr": report["cash_out_idr"],
        "net_cash_flow_idr": report["net_cash_flow_idr"],
        "ending_inventory_value_idr": report["ending_inventory"]["total_value_idr"],
        "sales_count": len(sale_ids),
        "purchases_count": len(purchase_ids),
    }

    # Minimum-necessary anonymized payload: NO workspace_id, workspace.name, actor_id, PII, or secrets.
    outbound_payload = {
        "snapshot_id": snapshot_id,
        "period": {
            "date": period["date"],
            "timezone": period["timezone"],
        },
        "currency": "IDR",
        "policy_version": report["policy_version"],
        "tax_status": report["tax_status"],
        "cost_status": report["cogs_status"],
        "metrics": metrics,
        "source_ids": source_ids_all,
    }

    data_sufficiency = (
        "insufficient_data"
        if metrics["sales_count"] == 0 and metrics["purchases_count"] == 0
        else "sufficient"
    )

    return {
        "snapshot_id": snapshot_id,
        "period": period,
        "policy_version": report["policy_version"],
        "tax_status": report["tax_status"],
        "cost_status": report["cogs_status"],
        "data_sufficiency": data_sufficiency,
        "metrics": metrics,
        "source_ids_all": source_ids_all,
        "outbound_payload": outbound_payload,
    }


def _collect_missing_data(snapshot: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    metrics = snapshot["metrics"]
    if metrics["cogs_status"] == "open":
        missing.append("cogs_open: HPP layanan/produk belum dinilai (open), laba kotor unavailable.")
    if snapshot["tax_status"] == "not_assessed":
        missing.append("tax_status: not_assessed (pajak belum dihitung).")
    if metrics["sales_count"] == 0 and metrics["purchases_count"] == 0:
        missing.append("no_transactions: Tidak ada transaksi penjualan atau pembelian pada periode ini.")
    return missing


def _build_deterministic_review(snapshot: dict[str, Any]) -> dict[str, Any]:
    m = snapshot["metrics"]
    period_date = snapshot["period"]["date"]
    cogs_text = f"Rp{m['cogs_idr']:,}" if m["cogs_idr"] is not None else "open (belum dinilai)"
    gp_text = f"Rp{m['gross_profit_idr']:,}" if m["gross_profit_idr"] is not None else "unavailable"
    summary = (
        f"Penjelasan AI belum tersedia. Ringkasan deterministik periode {period_date}: "
        f"Omzet Rp{m['revenue_idr']:,}, HPP {cogs_text}, Laba Kotor {gp_text}, "
        f"Arus Kas Bersih Rp{m['net_cash_flow_idr']:,}."
    )
    highlights = [
        f"Penjualan tercatat: {m['sales_count']} transaksi (Rp{m['revenue_idr']:,}).",
        f"Pembelian tercatat: {m['purchases_count']} transaksi; nilai stok akhir Rp{m['ending_inventory_value_idr']:,}.",
        f"Kas masuk Rp{m['cash_in_idr']:,}, kas keluar Rp{m['cash_out_idr']:,}.",
    ]
    return {
        "summary": summary,
        "highlights": highlights,
        "missing_data": _collect_missing_data(snapshot),
        "citations": {
            "snapshot_id": snapshot["snapshot_id"],
            "period_date": period_date,
            "source_ids": snapshot["source_ids_all"],
        },
    }


def validate_ai_output(raw_output: Any, snapshot: dict[str, Any]) -> tuple[bool, str | None]:
    """Strictly validate AI output against authoritative snapshot; never overwrite numbers."""
    if not isinstance(raw_output, dict):
        return False, "invalid_schema"
    summary = raw_output.get("summary")
    highlights = raw_output.get("highlights")
    missing_data = raw_output.get("missing_data")
    citations = raw_output.get("citations")

    if not isinstance(summary, str) or not summary.strip():
        return False, "empty_response"
    if not isinstance(highlights, list) or not all(isinstance(h, str) for h in highlights):
        return False, "invalid_schema"
    if not isinstance(missing_data, list) or not all(isinstance(d, str) for d in missing_data):
        return False, "invalid_schema"
    if not isinstance(citations, dict):
        return False, "invalid_schema"

    if citations.get("snapshot_id") != snapshot["snapshot_id"]:
        return False, "fake_citation"
    if citations.get("period_date") != snapshot["period"]["date"]:
        return False, "period_mismatch"

    cited_ids = citations.get("source_ids")
    if not isinstance(cited_ids, list) or not all(isinstance(x, str) for x in cited_ids):
        return False, "fake_citation"
    allowed_ids = set(snapshot["source_ids_all"])
    if allowed_ids and not cited_ids:
        return False, "fake_citation"
    if not set(cited_ids).issubset(allowed_ids):
        return False, "fake_citation"

    numeric_claims = raw_output.get("numeric_claims")
    if numeric_claims is not None:
        if not isinstance(numeric_claims, dict):
            return False, "numeric_mismatch"
        for k, v in numeric_claims.items():
            if k not in snapshot["metrics"] or isinstance(v, bool) or snapshot["metrics"][k] != v:
                return False, "numeric_mismatch"

    return True, None


def _run_stub_adapter(stub_mode: str, snapshot: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    outbound_payload = snapshot["outbound_payload"]
    if stub_mode == "stub_timeout":
        return None, "provider_timeout"
    if stub_mode == "stub_error":
        return None, "provider_error"
    if stub_mode == "stub_empty":
        return {"summary": "", "highlights": [], "missing_data": [], "citations": {}}, None
    if stub_mode == "stub_fake_citation":
        return {
            "summary": "Ringkasan stub dengan sitasi palsu.",
            "highlights": ["Klaim tidak valid."],
            "missing_data": [],
            "citations": {
                "snapshot_id": outbound_payload["snapshot_id"],
                "period_date": outbound_payload["period"]["date"],
                "source_ids": ["sale_fake_999999"],
            },
        }, None
    if stub_mode == "stub_wrong_period":
        return {
            "summary": "Ringkasan stub dengan periode salah.",
            "highlights": ["Periode tidak cocok."],
            "missing_data": [],
            "citations": {
                "snapshot_id": outbound_payload["snapshot_id"],
                "period_date": "1999-01-01",
                "source_ids": outbound_payload["source_ids"],
            },
        }, None
    # stub_valid
    m = outbound_payload["metrics"]
    return {
        "summary": (
            f"[Stub Test] Periode {outbound_payload['period']['date']}: "
            f"Omzet Rp{m['revenue_idr']:,}, Arus Kas Bersih Rp{m['net_cash_flow_idr']:,}."
        ),
        "highlights": [
            f"Total penjualan: {m['sales_count']} transaksi.",
            f"Status HPP: {m['cogs_status']}; status pajak: {outbound_payload['tax_status']}.",
        ],
        "missing_data": _collect_missing_data(snapshot),
        "citations": {
            "snapshot_id": outbound_payload["snapshot_id"],
            "period_date": outbound_payload["period"]["date"],
            "source_ids": outbound_payload["source_ids"],
        },
    }, None


def _call_gemini_adapter(
    outbound_payload: dict[str, Any],
    model: str,
    timeout_seconds: float,
) -> tuple[dict[str, Any] | None, str | None]:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return None, "provider_unconfigured"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    prompt = (
        "Anda adalah analis bisnis MarketStudio. Kembalikan HANYA JSON valid dengan keys: "
        "summary (string), highlights (list of strings), missing_data (list of strings), "
        "numeric_claims (object matching metrics), citations ({snapshot_id, period_date, source_ids}). "
        "Jangan mengubah angka. Gunakan hanya data berikut:\n"
        + json.dumps(outbound_payload)
    )
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw_text = resp.read().decode("utf-8")
        parsed = json.loads(raw_text)
        text = parsed["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text), None
    except urllib.error.HTTPError:
        return None, "provider_error"
    except (TimeoutError, urllib.error.URLError):
        return None, "provider_timeout"
    except Exception:
        return None, "provider_error"


def execute_ai_review(
    report: dict[str, Any],
    *,
    stub_mode: str | None = None,
    timeout_seconds: float = 8.0,
    provider_callable: Any = None,
) -> dict[str, Any]:
    """Execute AI Business Review with strict validation and deterministic fallback."""
    config_status = get_ai_provider_config_status()
    snapshot = build_metric_snapshot(report)
    outbound_payload = snapshot["outbound_payload"]

    raw_output: dict[str, Any] | None = None
    error_reason: str | None = None
    is_stub = stub_mode is not None

    if is_stub:
        raw_output, error_reason = _run_stub_adapter(stub_mode, snapshot)
    elif provider_callable is not None:
        try:
            raw_output = provider_callable(outbound_payload)
        except TimeoutError:
            error_reason = "provider_timeout"
        except Exception:
            error_reason = "provider_error"
    elif not config_status["configured"]:
        error_reason = "provider_unconfigured"
    else:
        raw_output, error_reason = _call_gemini_adapter(
            outbound_payload,
            model=str(config_status["model"]),
            timeout_seconds=timeout_seconds,
        )

    if error_reason is None:
        valid, validation_reason = validate_ai_output(raw_output, snapshot)
        if not valid:
            error_reason = validation_reason

    if error_reason is not None:
        return {
            "status": "fallback",
            "provider_mode": "deterministic_fallback",
            "fallback_reason": error_reason,
            "is_stub": is_stub,
            "stub_mode": stub_mode,
            "config_status": config_status,
            "snapshot": {
                "snapshot_id": snapshot["snapshot_id"],
                "period": snapshot["period"],
                "policy_version": snapshot["policy_version"],
                "tax_status": snapshot["tax_status"],
                "cost_status": snapshot["cost_status"],
                "metrics": snapshot["metrics"],
                "source_ids": snapshot["source_ids_all"],
            },
            "review": _build_deterministic_review(snapshot),
        }

    return {
        "status": "succeeded",
        "provider_mode": "stub_test" if is_stub else "live_provider",
        "fallback_reason": None,
        "is_stub": is_stub,
        "stub_mode": stub_mode,
        "config_status": config_status,
        "snapshot": {
            "snapshot_id": snapshot["snapshot_id"],
            "period": snapshot["period"],
            "policy_version": snapshot["policy_version"],
            "tax_status": snapshot["tax_status"],
            "cost_status": snapshot["cost_status"],
            "metrics": snapshot["metrics"],
            "source_ids": snapshot["source_ids_all"],
        },
        "review": raw_output,
    }
