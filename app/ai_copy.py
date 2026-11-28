"""Compose offering copy from local facts and bounded provider output."""

import json
import os
from typing import Any

from app.ai_review import call_gemini_json, get_ai_provider_config_status
from app.domain import DomainError

PROMPT_VERSION = "creative-copy-v1"
TONES = ("friendly", "direct")
CATEGORIES = {"goods": "Barang", "service": "Jasa", "hybrid": "Barang dan jasa"}
OPENINGS = {
    "friendly": {
        "discover": "Kenali {name}",
        "invite": "Yuk, lihat {name}",
    },
    "direct": {
        "introduce": "Pilihan kami: {name}",
        "describe": "Tentang {name}",
    },
}
CLOSINGS = {
    "friendly": {
        "ask": "Yuk, tanyakan detailnya.",
        "contact": "Hubungi kami untuk tahu lebih lanjut.",
    },
    "direct": {
        "details": "Hubungi kami untuk informasi lebih lanjut.",
        "ask": "Tanyakan detail produk atau jasa ini kepada kami.",
    },
}


def generate_copy(facts: dict[str, Any], tone: str) -> tuple[str, str, dict[str, Any]]:
    """The provider chooses phrasing IDs. Factual text is assembled server-side."""
    template_choices = {
        "opening": list(OPENINGS[tone]),
        "closing": list(CLOSINGS[tone]),
    }
    config = get_ai_provider_config_status()
    stub = (
        os.environ.get("MARKETSTUDIO_AI_COPY_STUB")
        if os.environ.get("MARKETSTUDIO_ENV") != "production"
        else None
    )
    if stub not in ("stub_valid", "stub_timeout", "stub_error"):
        stub = None
    if stub == "stub_valid":
        output, reason = {key: ids[0] for key, ids in template_choices.items()}, None
    elif stub in ("stub_timeout", "stub_error"):
        output, reason = None, stub.replace("stub_", "provider_")
    elif config["configured"]:
        # Share only category and editorial choices. Offering text stays local.
        prompt = (
            "Pilih gaya pembuka dan penutup promosi yang cocok. Kembalikan objek JSON "
            "dengan dua key opening dan closing, masing-masing berisi salah satu ID "
            "pilihan yang diberikan.\n"
            + json.dumps({
                "tone": tone,
                "category": facts["offering_type"],
                "choices": template_choices,
            })
        )
        output, reason = call_gemini_json(prompt, config["model"], 8.0)
    else:
        output, reason = None, "provider_unconfigured"

    if reason is None and (
        not isinstance(output, dict)
        or set(output) != set(template_choices)
        or any(output[key] not in choices for key, choices in template_choices.items())
    ):
        reason = "invalid_provider_output"
    if reason is not None:
        prefix = "Simulasi: " if stub else ""
        raise DomainError(
            503, reason,
            prefix + "AI belum dapat membuat caption. Coba lagi atau pilih Tulis manual.",
        )

    name = facts["name"]
    opening = OPENINGS[tone][output["opening"]]
    headline = opening.format(name=name if len(name) <= 110 else name[:109] + "…")
    category = CATEGORIES[facts["offering_type"]]
    price = f'Rp {facts["unit_price_idr"]:,}'.replace(",", ".")
    unit = f' / {facts["unit"]}' if len(facts["unit"]) <= 80 else ""
    caption = "\n".join(filter(None, [
        f'{headline}.',
        f'{category} · Harga jual per satuan: {price}{unit}',
        facts["description"],
        CLOSINGS[tone][output["closing"]],
    ]))
    return headline, caption, {
        "prompt_version": PROMPT_VERSION,
        "tone": tone,
        "provider_mode": "stub_test" if stub else "live_provider",
        "provider": "stub" if stub else config["provider"],
        "model": None if stub else config["model"],
        "template": output,
    }
