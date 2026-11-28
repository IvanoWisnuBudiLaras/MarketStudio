"""Creative Studio (#42) domain logic: licensed local assets, poster drafts, and pure-Python SVG/PNG rendering."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from app.domain import DomainError

SUPPORTED_EXPORT_FORMATS = ("svg", "png")
SIMULATE_FAILURE_MODES = ("missing_file", "corrupt_file", "unlicensed")
VALID_COPY_SOURCES = ("manual", "sample", "ai_copy")

DEFAULT_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "creative"

LICENSED_LOCAL_ASSETS: tuple[dict[str, Any], ...] = (
    {
        "asset_id": "asset_bakso_bowl_v1",
        "title": "Ilustrasi Mangkuk Bakso Hangat (Sample CC0)",
        "mime_type": "image/png",
        "filename": "bakso-bowl-sample.png",
        "sha256": "e8eb33beb8c66e38d988a47642287335c1ae4bebf347db41e92245eb20edc4d9",
        "asset_source": "marketstudio_local_sample",
        "asset_license": "CC0-1.0",
        "license_status": "verified",
        "attribution_text": "MarketStudio Synthetic Sample Asset — CC0-1.0 Public Domain",
        "asset_provenance": {
            "origin": "in_repo_synthetic_sample",
            "creator": "MarketStudio Creative Studio Baseline",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "is_synthetic_sample": True,
            "verified_by": "marketstudio_registry",
            "compatible_with": ["goods", "hybrid"],
        },
        "is_builtin": True,
    },
    {
        "asset_id": "asset_beras_harvest_v1",
        "title": "Ilustrasi Karung Beras & Padi (Sample CC0)",
        "mime_type": "image/png",
        "filename": "beras-harvest-sample.png",
        "sha256": "a7ed1c182d74254b5caa56d793e4e77ff1e7b9d60fba5e14369c1172bf0c8b49",
        "asset_source": "marketstudio_local_sample",
        "asset_license": "CC0-1.0",
        "license_status": "verified",
        "attribution_text": "MarketStudio Synthetic Sample Asset — CC0-1.0 Public Domain",
        "asset_provenance": {
            "origin": "in_repo_synthetic_sample",
            "creator": "MarketStudio Creative Studio Baseline",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "is_synthetic_sample": True,
            "verified_by": "marketstudio_registry",
            "compatible_with": ["goods", "hybrid"],
        },
        "is_builtin": True,
    },
    {
        "asset_id": "asset_catering_tray_v1",
        "title": "Ilustrasi Sajian Katering Acara (Sample CC0)",
        "mime_type": "image/png",
        "filename": "catering-tray-sample.png",
        "sha256": "5eedddd4bc5a0304885153e4e20f748bc9f417dea1fc38c8d7619ee2fc9c8a07",
        "asset_source": "marketstudio_local_sample",
        "asset_license": "CC0-1.0",
        "license_status": "verified",
        "attribution_text": "MarketStudio Synthetic Sample Asset — CC0-1.0 Public Domain",
        "asset_provenance": {
            "origin": "in_repo_synthetic_sample",
            "creator": "MarketStudio Creative Studio Baseline",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "is_synthetic_sample": True,
            "verified_by": "marketstudio_registry",
            "compatible_with": ["service", "hybrid"],
        },
        "is_builtin": True,
    },
)

BUILTIN_ASSET_MAP: dict[str, dict[str, Any]] = {
    item["asset_id"]: item for item in LICENSED_LOCAL_ASSETS
}

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MAX_ASSET_BYTES = 8 * 1024 * 1024
_SAFE_FILE_RE = re.compile(r"[^A-Za-z0-9_.-]+")

# Compact 5x7 ASCII bitmap font (32..126) for pure-Python PNG poster rendering.
_FONT_5X7: dict[str, tuple[int, ...]] = {
    " ": (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
    "!": (0x04, 0x04, 0x04, 0x04, 0x04, 0x00, 0x04),
    '"': (0x0A, 0x0A, 0x0A, 0x00, 0x00, 0x00, 0x00),
    "#": (0x0A, 0x0A, 0x1F, 0x0A, 0x1F, 0x0A, 0x0A),
    "$": (0x04, 0x0F, 0x14, 0x0E, 0x05, 0x1E, 0x04),
    "%": (0x18, 0x19, 0x02, 0x04, 0x08, 0x13, 0x03),
    "&": (0x0C, 0x12, 0x14, 0x08, 0x15, 0x12, 0x0D),
    "'": (0x04, 0x04, 0x08, 0x00, 0x00, 0x00, 0x00),
    "(": (0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02),
    ")": (0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08),
    "*": (0x00, 0x04, 0x15, 0x0E, 0x15, 0x04, 0x00),
    "+": (0x00, 0x04, 0x04, 0x1F, 0x04, 0x04, 0x00),
    ",": (0x00, 0x00, 0x00, 0x00, 0x04, 0x04, 0x08),
    "-": (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00),
    ".": (0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C),
    "/": (0x01, 0x02, 0x02, 0x04, 0x08, 0x08, 0x10),
    "0": (0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E),
    "1": (0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "2": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F),
    "3": (0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E),
    "4": (0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02),
    "5": (0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E),
    "6": (0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E),
    "7": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08),
    "8": (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E),
    "9": (0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C),
    ":": (0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x0C, 0x00),
    ";": (0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x04, 0x08),
    "<": (0x02, 0x04, 0x08, 0x10, 0x08, 0x04, 0x02),
    "=": (0x00, 0x00, 0x1F, 0x00, 0x1F, 0x00, 0x00),
    ">": (0x08, 0x04, 0x02, 0x01, 0x02, 0x04, 0x08),
    "?": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x00, 0x04),
    "@": (0x0E, 0x11, 0x17, 0x15, 0x17, 0x10, 0x0E),
    "A": (0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "B": (0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E),
    "C": (0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E),
    "D": (0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E),
    "E": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F),
    "F": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10),
    "G": (0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F),
    "H": (0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "I": (0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "J": (0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C),
    "K": (0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11),
    "L": (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F),
    "M": (0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11),
    "N": (0x11, 0x11, 0x19, 0x15, 0x13, 0x11, 0x11),
    "O": (0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "P": (0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10),
    "Q": (0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D),
    "R": (0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11),
    "S": (0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E),
    "T": (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    "U": (0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "V": (0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04),
    "W": (0x11, 0x11, 0x11, 0x15, 0x15, 0x1B, 0x11),
    "X": (0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11),
    "Y": (0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04),
    "Z": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F),
    "[": (0x0E, 0x08, 0x08, 0x08, 0x08, 0x08, 0x0E),
    "\\": (0x10, 0x08, 0x08, 0x04, 0x02, 0x02, 0x01),
    "]": (0x0E, 0x02, 0x02, 0x02, 0x02, 0x02, 0x0E),
    "^": (0x04, 0x0A, 0x11, 0x00, 0x00, 0x00, 0x00),
    "_": (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x1F),
    "`": (0x08, 0x04, 0x02, 0x00, 0x00, 0x00, 0x00),
    "a": (0x00, 0x00, 0x0E, 0x01, 0x0F, 0x11, 0x0F),
    "b": (0x10, 0x10, 0x16, 0x19, 0x11, 0x11, 0x1E),
    "c": (0x00, 0x00, 0x0E, 0x10, 0x10, 0x11, 0x0E),
    "d": (0x01, 0x01, 0x0D, 0x13, 0x11, 0x11, 0x0F),
    "e": (0x00, 0x00, 0x0E, 0x11, 0x1F, 0x10, 0x0E),
    "f": (0x06, 0x09, 0x08, 0x1C, 0x08, 0x08, 0x08),
    "g": (0x00, 0x0F, 0x11, 0x11, 0x0F, 0x01, 0x0E),
    "h": (0x10, 0x10, 0x16, 0x19, 0x11, 0x11, 0x11),
    "i": (0x04, 0x00, 0x0C, 0x04, 0x04, 0x04, 0x0E),
    "j": (0x02, 0x00, 0x06, 0x02, 0x02, 0x12, 0x0C),
    "k": (0x10, 0x10, 0x12, 0x14, 0x18, 0x14, 0x12),
    "l": (0x0C, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "m": (0x00, 0x00, 0x1A, 0x15, 0x15, 0x11, 0x11),
    "n": (0x00, 0x00, 0x16, 0x19, 0x11, 0x11, 0x11),
    "o": (0x00, 0x00, 0x0E, 0x11, 0x11, 0x11, 0x0E),
    "p": (0x00, 0x00, 0x1E, 0x11, 0x1E, 0x10, 0x10),
    "q": (0x00, 0x00, 0x0D, 0x13, 0x0F, 0x01, 0x01),
    "r": (0x00, 0x00, 0x16, 0x19, 0x10, 0x10, 0x10),
    "s": (0x00, 0x00, 0x0E, 0x10, 0x0E, 0x01, 0x1E),
    "t": (0x08, 0x08, 0x1C, 0x08, 0x08, 0x09, 0x06),
    "u": (0x00, 0x00, 0x11, 0x11, 0x11, 0x13, 0x0D),
    "v": (0x00, 0x00, 0x11, 0x11, 0x11, 0x0A, 0x04),
    "w": (0x00, 0x00, 0x11, 0x11, 0x15, 0x15, 0x0A),
    "x": (0x00, 0x00, 0x11, 0x0A, 0x04, 0x0A, 0x11),
    "y": (0x00, 0x00, 0x11, 0x11, 0x0F, 0x01, 0x0E),
    "z": (0x00, 0x00, 0x1F, 0x02, 0x04, 0x08, 0x1F),
    "{": (0x02, 0x04, 0x04, 0x08, 0x04, 0x04, 0x02),
    "|": (0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    "}": (0x08, 0x04, 0x04, 0x02, 0x04, 0x04, 0x08),
    "~": (0x00, 0x08, 0x15, 0x02, 0x00, 0x00, 0x00),
}


@dataclass(frozen=True)
class LoadedAsset:
    asset_id: str
    title: str
    mime_type: str
    asset_source: str
    asset_license: str
    license_status: str
    attribution_text: str
    asset_provenance: dict[str, Any]
    raw_bytes: bytes
    sha256: str
    width: int
    height: int
    rgb_bytes: bytes


def _strip_ctrl(text: str) -> str:
    return _CTRL_RE.sub("", text)


def _xml_text(value: Any) -> str:
    return xml_escape(_strip_ctrl(str(value or "")), {'"': "&quot;", "'": "&#39;"})


def _safe_filename(name: str) -> str:
    cleaned = _SAFE_FILE_RE.sub("-", name.strip())
    return cleaned.strip("-.") or "poster"


def compute_draft_revision_hash(draft: dict[str, Any]) -> str:
    """Compute canonical SHA-256 revision hash binding draft content, asset, and version."""
    canonical_payload = {
        "draft_id": draft["draft_id"],
        "workspace_id": draft["workspace_id"],
        "offering_id": draft.get("offering_id"),
        "title": draft["title"],
        "headline": draft["headline"],
        "caption": draft.get("caption", ""),
        "cta_text": draft.get("cta_text", ""),
        "price_label": draft.get("price_label", ""),
        "copy_source": draft.get("copy_source", "manual"),
        "asset_id": draft["asset_id"],
        "asset_source": draft["asset_source"],
        "asset_license": draft["asset_license"],
        "version": int(draft["version"]),
    }
    encoded = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_str_field(
    payload: dict[str, Any],
    field: str,
    *,
    required: bool,
    min_len: int = 0,
    max_len: int = 200,
    errors: dict[str, str],
) -> str | None:
    if field not in payload:
        if required:
            errors[field] = f"{field} wajib diisi."
        return None
    raw = payload.get(field)
    if raw is None:
        if required:
            errors[field] = f"{field} wajib diisi."
            return None
        return ""
    if not isinstance(raw, str):
        errors[field] = f"{field} harus berupa string."
        return None
    val = _strip_ctrl(raw).strip()
    if required and not val:
        errors[field] = f"{field} tidak boleh kosong."
        return None
    if val and len(val) < min_len:
        errors[field] = f"{field} minimal {min_len} karakter."
        return None
    if len(val) > max_len:
        errors[field] = f"{field} maksimal {max_len} karakter."
        return None
    return val


def validate_poster_draft_input(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    """Validate create or partial update payload for a poster draft (draft-only invariant)."""
    errors: dict[str, str] = {}
    cleaned: dict[str, Any] = {}

    if "status" in payload and payload.get("status") not in (None, "draft"):
        errors["status"] = "Status poster hanya boleh 'draft' (ekspor tidak melakukan publish)."

    title = _validate_str_field(
        payload, "title", required=not partial, min_len=2, max_len=120, errors=errors
    )
    if title is not None and (not partial or "title" in payload):
        if partial and not title:
            errors["title"] = "title tidak boleh kosong."
        else:
            cleaned["title"] = title

    headline = _validate_str_field(
        payload, "headline", required=not partial, min_len=2, max_len=140, errors=errors
    )
    if headline is not None and (not partial or "headline" in payload):
        if partial and not headline:
            errors["headline"] = "headline tidak boleh kosong."
        else:
            cleaned["headline"] = headline

    caption = _validate_str_field(
        payload, "caption", required=False, min_len=0, max_len=600, errors=errors
    )
    if caption is not None and (not partial or "caption" in payload):
        cleaned["caption"] = caption
    elif not partial:
        cleaned["caption"] = ""

    cta_text = _validate_str_field(
        payload, "cta_text", required=False, min_len=0, max_len=80, errors=errors
    )
    if cta_text is not None and (not partial or "cta_text" in payload):
        cleaned["cta_text"] = cta_text
    elif not partial:
        cleaned["cta_text"] = ""

    price_label = _validate_str_field(
        payload, "price_label", required=False, min_len=0, max_len=60, errors=errors
    )
    if price_label is not None and (not partial or "price_label" in payload):
        cleaned["price_label"] = price_label
    elif not partial:
        cleaned["price_label"] = ""

    if "asset_id" in payload or not partial:
        raw_asset = payload.get("asset_id")
        if not isinstance(raw_asset, str) or not raw_asset.strip():
            errors["asset_id"] = "asset_id wajib diisi dengan aset berizin."
        else:
            cleaned["asset_id"] = raw_asset.strip()

    if "offering_id" in payload:
        raw_off = payload.get("offering_id")
        if raw_off is None or (isinstance(raw_off, str) and not raw_off.strip()):
            cleaned["offering_id"] = None
        elif not isinstance(raw_off, str):
            errors["offering_id"] = "offering_id harus berupa string atau null."
        else:
            cleaned["offering_id"] = raw_off.strip()
    elif not partial:
        cleaned["offering_id"] = None

    if "copy_source" in payload:
        raw_cs = payload.get("copy_source")
        if raw_cs not in VALID_COPY_SOURCES:
            errors["copy_source"] = f"copy_source harus salah satu dari: {', '.join(VALID_COPY_SOURCES)}."
        else:
            cleaned["copy_source"] = raw_cs
    elif not partial:
        cleaned["copy_source"] = "manual"

    if "copy_provenance" in payload:
        raw_cp = payload.get("copy_provenance")
        if raw_cp is not None and not isinstance(raw_cp, dict):
            errors["copy_provenance"] = "copy_provenance harus berupa JSON object atau null."
        else:
            cleaned["copy_provenance"] = raw_cp
    elif not partial:
        cleaned["copy_provenance"] = None

    if partial and "expected_version" in payload and payload.get("expected_version") is not None:
        raw_ev = payload.get("expected_version")
        if isinstance(raw_ev, bool) or not isinstance(raw_ev, int) or raw_ev < 1:
            errors["expected_version"] = "expected_version harus bilangan bulat >= 1."
        else:
            cleaned["expected_version"] = raw_ev

    if partial:
        editable_keys = (
            "title",
            "headline",
            "caption",
            "cta_text",
            "price_label",
            "asset_id",
            "offering_id",
            "copy_source",
            "copy_provenance",
        )
        if not any(k in cleaned for k in editable_keys) and not errors:
            errors["payload"] = "Minimal satu field draft poster wajib diubah."

    if errors:
        raise DomainError(422, "validation_error", "Data draft poster tidak valid.", errors)
    return cleaned


def _validate_simulate_failure(raw: Any) -> str | None:
    if raw is None or raw == "":
        return None
    if os.environ.get("MARKETSTUDIO_ENV") == "production" and os.environ.get("MARKETSTUDIO_ENABLE_TEST_FAULTS") != "1":
        raise DomainError(403, "test_fault_disabled", "Simulasi kegagalan aset dinonaktifkan di production.")
    if not isinstance(raw, str) or raw not in SIMULATE_FAILURE_MODES:
        raise DomainError(
            422,
            "invalid_failure_mode",
            f"simulate_asset_failure tidak dikenal. Pilihan: {', '.join(SIMULATE_FAILURE_MODES)}.",
            {"simulate_asset_failure": "Mode simulasi kegagalan tidak valid."},
        )
    return raw


def validate_preview_request(payload: dict[str, Any] | None) -> tuple[str, str | None]:
    body = payload if isinstance(payload, dict) else {}
    raw_fmt = body.get("format", "svg")
    if not isinstance(raw_fmt, str) or raw_fmt.strip().lower() not in SUPPORTED_EXPORT_FORMATS:
        raise DomainError(
            422,
            "unsupported_export_format",
            f"Format poster tidak didukung. Pilihan: {', '.join(SUPPORTED_EXPORT_FORMATS)}.",
            {"format": "Format harus 'svg' atau 'png'."},
        )
    sim_fail = _validate_simulate_failure(body.get("simulate_asset_failure"))
    return raw_fmt.strip().lower(), sim_fail


def validate_export_request(payload: dict[str, Any]) -> tuple[str, int, str | None, str, str | None]:
    errors: dict[str, str] = {}
    raw_fmt = payload.get("format")
    if not isinstance(raw_fmt, str) or raw_fmt.strip().lower() not in SUPPORTED_EXPORT_FORMATS:
        errors["format"] = f"format wajib salah satu dari: {', '.join(SUPPORTED_EXPORT_FORMATS)}."

    raw_ver = payload.get("expected_version")
    if isinstance(raw_ver, bool) or not isinstance(raw_ver, int) or raw_ver < 1:
        errors["expected_version"] = "expected_version wajib berupa integer >= 1 sesuai versi yang dipratinjau."

    raw_hash = payload.get("expected_revision_hash")
    expected_hash: str | None = None
    if raw_hash is not None:
        if not isinstance(raw_hash, str) or not raw_hash.strip():
            errors["expected_revision_hash"] = "expected_revision_hash harus berupa string non-kosong."
        else:
            expected_hash = raw_hash.strip()

    preview_sha256 = payload.get("preview_sha256")
    if not isinstance(preview_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", preview_sha256):
        errors["preview_sha256"] = "Gunakan SHA-256 dari hasil pratinjau poster."

    if errors:
        raise DomainError(422, "validation_error", "Permintaan ekspor poster tidak valid.", errors)

    sim_fail = _validate_simulate_failure(payload.get("simulate_asset_failure"))
    return raw_fmt.strip().lower(), int(raw_ver), expected_hash, preview_sha256, sim_fail


def _paeth_predictor(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def decode_png_rgb(raw_bytes: bytes) -> tuple[int, int, bytes]:
    """Verify PNG signature, chunk CRCs, and decode 8-bit RGB/RGBA non-interlaced PNG to RGB bytes."""
    if not isinstance(raw_bytes, (bytes, bytearray)) or len(raw_bytes) < 33:
        raise ValueError("Berkas PNG terlalu kecil atau kosong.")
    if raw_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Signature PNG tidak valid.")

    pos = 8
    width = 0
    height = 0
    bit_depth = 0
    color_type = -1
    saw_ihdr = False
    saw_iend = False
    idat_parts: list[bytes] = []

    while pos < len(raw_bytes):
        if pos + 12 > len(raw_bytes):
            raise ValueError("Header chunk PNG terpotong.")
        length = struct.unpack(">I", raw_bytes[pos : pos + 4])[0]
        chunk_type = raw_bytes[pos + 4 : pos + 8]
        data_start = pos + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > len(raw_bytes):
            raise ValueError("Data chunk PNG terpotong.")
        chunk_data = raw_bytes[data_start:data_end]
        expected_crc = struct.unpack(">I", raw_bytes[data_end:crc_end])[0]
        actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError(f"CRC chunk PNG rusak pada {chunk_type!r}.")

        if chunk_type == b"IHDR":
            if saw_ihdr or len(chunk_data) != 13:
                raise ValueError("Chunk IHDR PNG tidak valid.")
            width, height, bit_depth, color_type, comp, flt, interlace = struct.unpack(">IIBBBBB", chunk_data)
            if width <= 0 or height <= 0 or width > 4096 or height > 4096:
                raise ValueError("Dimensi PNG di luar batas aman.")
            if bit_depth != 8 or color_type not in (2, 6):
                raise ValueError("Hanya PNG 8-bit RGB/RGBA yang didukung.")
            if comp != 0 or flt != 0 or interlace != 0:
                raise ValueError("Format kompresi/interlace PNG tidak didukung.")
            saw_ihdr = True
        elif chunk_type == b"IDAT":
            if not saw_ihdr:
                raise ValueError("IDAT muncul sebelum IHDR.")
            idat_parts.append(chunk_data)
        elif chunk_type == b"IEND":
            saw_iend = True
            pos = crc_end
            break

        pos = crc_end

    if not saw_ihdr or not saw_iend or not idat_parts:
        raise ValueError("Struktur PNG tidak lengkap (IHDR/IDAT/IEND).")

    channels = 3 if color_type == 2 else 4
    stride = width * channels
    expected_len = height * (1 + stride)
    decoder = zlib.decompressobj()
    raw_scanlines = decoder.decompress(b"".join(idat_parts), expected_len + 1)
    if len(raw_scanlines) != expected_len or not decoder.eof or decoder.unused_data:
        raise ValueError("Panjang data piksel PNG tidak sesuai dengan dimensi IHDR.")

    unfiltered = bytearray(height * stride)
    prev_row = bytes(stride)
    for y in range(height):
        row_start = y * (1 + stride)
        ftype = raw_scanlines[row_start]
        src = raw_scanlines[row_start + 1 : row_start + 1 + stride]
        dst = bytearray(stride)
        if ftype == 0:
            dst[:] = src
        elif ftype == 1:
            for i in range(stride):
                left = dst[i - channels] if i >= channels else 0
                dst[i] = (src[i] + left) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                dst[i] = (src[i] + prev_row[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = dst[i - channels] if i >= channels else 0
                up = prev_row[i]
                dst[i] = (src[i] + ((left + up) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                left = dst[i - channels] if i >= channels else 0
                up = prev_row[i]
                up_left = prev_row[i - channels] if i >= channels else 0
                dst[i] = (src[i] + _paeth_predictor(left, up, up_left)) & 0xFF
        else:
            raise ValueError(f"Filter PNG tidak dikenal: {ftype}")

        unfiltered[y * stride : (y + 1) * stride] = dst
        prev_row = bytes(dst)

    if channels == 3:
        return width, height, bytes(unfiltered)

    # Alpha-composite RGBA onto crisp white background
    rgb = bytearray(width * height * 3)
    for idx in range(width * height):
        r, g, b, a = unfiltered[idx * 4 : idx * 4 + 4]
        out_i = idx * 3
        if a == 255:
            rgb[out_i] = r
            rgb[out_i + 1] = g
            rgb[out_i + 2] = b
        elif a == 0:
            rgb[out_i] = 255
            rgb[out_i + 1] = 255
            rgb[out_i + 2] = 255
        else:
            inv = 255 - a
            rgb[out_i] = (r * a + 255 * inv + 127) // 255
            rgb[out_i + 1] = (g * a + 255 * inv + 127) // 255
            rgb[out_i + 2] = (b * a + 255 * inv + 127) // 255
    return width, height, bytes(rgb)


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def _latin1_text_bytes(value: str) -> bytes:
    cleaned = _strip_ctrl(value).replace("\r", " ").replace("\n", " ")
    return cleaned.encode("latin-1", errors="replace")


def encode_png_rgb(
    width: int,
    height: int,
    rgb_bytes: bytes,
    text_chunks: dict[str, str] | None = None,
) -> bytes:
    """Encode 8-bit RGB bytes plus optional tEXt provenance chunks into a valid PNG."""
    stride = width * 3
    if len(rgb_bytes) != height * stride:
        raise ValueError("Ukuran buffer RGB tidak sesuai dengan width*height*3.")

    parts: list[bytes] = [
        b"\x89PNG\r\n\x1a\n",
        _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
    ]
    if text_chunks:
        for key, val in text_chunks.items():
            k_bytes = _latin1_text_bytes(key)[:79].strip(b" ")
            v_bytes = _latin1_text_bytes(val)
            if k_bytes:
                parts.append(_png_chunk(b"tEXt", k_bytes + b"\x00" + v_bytes))

    scanlines = bytearray(height * (1 + stride))
    for y in range(height):
        dst_start = y * (1 + stride)
        scanlines[dst_start] = 0
        src_start = y * stride
        scanlines[dst_start + 1 : dst_start + 1 + stride] = rgb_bytes[src_start : src_start + stride]

    compressed = zlib.compress(bytes(scanlines), level=6)
    parts.append(_png_chunk(b"IDAT", compressed))
    parts.append(_png_chunk(b"IEND", b""))
    return b"".join(parts)


def load_and_verify_asset(
    asset_record: dict[str, Any],
    assets_root: Path | str,
    simulate_failure: str | None = None,
) -> LoadedAsset:
    """Verify asset licensing metadata and decode image bytes safely without leaking broken output."""
    if simulate_failure == "unlicensed":
        raise DomainError(
            422,
            "unlicensed_asset",
            "Simulasi kegagalan lisensi: aset tidak memiliki status lisensi terverifikasi.",
        )
    if simulate_failure == "missing_file":
        raise DomainError(
            503,
            "asset_load_failed",
            "Gagal memuat aset poster: berkas aset tidak ditemukan (simulasi missing_file).",
        )
    if simulate_failure == "corrupt_file":
        raise DomainError(
            503,
            "asset_load_failed",
            "Gagal memuat aset poster: berkas gambar rusak atau tidak valid (simulasi corrupt_file).",
        )

    license_status = str(asset_record.get("license_status") or "").strip().lower()
    asset_license = str(asset_record.get("asset_license") or "").strip()
    asset_source = str(asset_record.get("asset_source") or "").strip()
    attribution_text = str(asset_record.get("attribution_text") or "").strip()

    if license_status != "verified" or not asset_license or not asset_source or not attribution_text:
        raise DomainError(
            422,
            "unlicensed_asset",
            "Aset poster belum memiliki lisensi terverifikasi atau metadata sumber tidak lengkap.",
            {"asset_id": "Aset harus memiliki lisensi terverifikasi sebelum pratinjau/ekspor."},
        )

    try:
        raw_bytes = asset_record.get("png")
        if raw_bytes is None:
            rel_path = str(asset_record.get("file_path") or asset_record.get("filename") or "").strip()
            if not rel_path or Path(rel_path).is_absolute():
                raise DomainError(
                    503,
                    "asset_load_failed",
                    "Gagal memuat aset poster: path berkas aset tidak valid.",
                )

            root_resolved = Path(assets_root).resolve()
            candidate = (root_resolved / rel_path).resolve()
            if not candidate.is_relative_to(root_resolved) or not candidate.is_file():
                raise DomainError(
                    503,
                    "asset_load_failed",
                    f"Gagal memuat aset poster: berkas '{rel_path}' tidak ditemukan atau tidak dapat diakses.",
                )
            with candidate.open("rb") as file:
                raw_bytes = file.read(_MAX_ASSET_BYTES + 1)
        if len(raw_bytes) > _MAX_ASSET_BYTES:
            raise ValueError("Ukuran PNG melebihi 8 MiB.")
        digest = hashlib.sha256(raw_bytes).hexdigest()
        if asset_record.get("sha256") and digest != asset_record["sha256"]:
            raise ValueError("Berkas berbeda dari aset contoh yang terverifikasi.")
        width, height, rgb_bytes = decode_png_rgb(raw_bytes)
    except (OSError, ValueError, struct.error, zlib.error) as exc:
        raise DomainError(
            503,
            "asset_load_failed",
            f"Gagal memuat aset poster '{asset_record.get('asset_id', '')}': berkas gambar rusak ({exc}).",
        ) from exc

    return LoadedAsset(
        asset_id=str(asset_record["asset_id"]),
        title=str(asset_record.get("title") or asset_record["asset_id"]),
        mime_type="image/png",
        asset_source=asset_source,
        asset_license=asset_license,
        license_status=license_status,
        attribution_text=attribution_text,
        asset_provenance=dict(asset_record.get("asset_provenance") or {}),
        raw_bytes=raw_bytes,
        sha256=digest,
        width=width,
        height=height,
        rgb_bytes=rgb_bytes,
    )


def _wrap_text(text: str, max_chars: int, max_lines: int) -> list[str]:
    clean = " ".join(_strip_ctrl(text).split())
    if not clean:
        return []
    words = clean.split(" ")
    lines: list[str] = []
    cur = ""
    for word in words:
        while len(word) > max_chars:
            if cur:
                lines.append(cur)
                cur = ""
                if len(lines) >= max_lines:
                    return lines[:max_lines]
            lines.append(word[: max_chars - 1] + "-")
            word = word[max_chars - 1 :]
            if len(lines) >= max_lines:
                return lines[:max_lines]
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= max_chars:
            cur = f"{cur} {word}"
        else:
            lines.append(cur)
            cur = word
            if len(lines) >= max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    return lines


def _ascii_norm(text: str) -> str:
    return (
        text.replace("—", "-")
        .replace("–", "-")
        .replace("•", "-")
        .replace("“", '"')
        .replace("”", '"')
        .replace("’", "'")
        .replace("‘", "'")
    )


def _fill_rect(buf: bytearray, w: int, h: int, x0: int, y0: int, rw: int, rh: int, rgb: tuple[int, int, int]) -> None:
    x_start = max(0, x0)
    y_start = max(0, y0)
    x_end = min(w, x0 + rw)
    y_end = min(h, y0 + rh)
    if x_end <= x_start or y_end <= y_start:
        return
    span = x_end - x_start
    row_bytes = bytes(rgb) * span
    stride = w * 3
    for y in range(y_start, y_end):
        off = y * stride + x_start * 3
        buf[off : off + span * 3] = row_bytes


def _stroke_rect(
    buf: bytearray, w: int, h: int, x0: int, y0: int, rw: int, rh: int, thickness: int, rgb: tuple[int, int, int]
) -> None:
    _fill_rect(buf, w, h, x0, y0, rw, thickness, rgb)
    _fill_rect(buf, w, h, x0, y0 + rh - thickness, rw, thickness, rgb)
    _fill_rect(buf, w, h, x0, y0, thickness, rh, rgb)
    _fill_rect(buf, w, h, x0 + rw - thickness, y0, thickness, rh, rgb)


def _draw_text_rgb(
    buf: bytearray,
    w: int,
    h: int,
    x: int,
    y: int,
    text: str,
    scale: int,
    rgb: tuple[int, int, int],
) -> None:
    clean = _ascii_norm(_strip_ctrl(text))
    cursor_x = x
    advance = 6 * scale
    col = bytes(rgb)
    stride = w * 3
    for ch in clean:
        glyph = _FONT_5X7.get(ch) or _FONT_5X7["?"]
        for row_idx, bits in enumerate(glyph):
            py_base = y + row_idx * scale
            if py_base + scale <= 0 or py_base >= h:
                continue
            for col_idx in range(5):
                if bits & (1 << (4 - col_idx)):
                    px_base = cursor_x + col_idx * scale
                    if px_base + scale <= 0 or px_base >= w:
                        continue
                    for sy in range(scale):
                        py = py_base + sy
                        if 0 <= py < h:
                            for sx in range(scale):
                                px = px_base + sx
                                if 0 <= px < w:
                                    off = py * stride + px * 3
                                    buf[off : off + 3] = col
        cursor_x += advance


def _blit_scaled_rgb(
    dst: bytearray,
    dst_w: int,
    dst_h: int,
    dst_x: int,
    dst_y: int,
    target_w: int,
    target_h: int,
    src_rgb: bytes,
    src_w: int,
    src_h: int,
) -> None:
    dst_stride = dst_w * 3
    src_stride = src_w * 3
    for ty in range(target_h):
        py = dst_y + ty
        if not (0 <= py < dst_h):
            continue
        sy = (ty * src_h) // target_h
        src_row = sy * src_stride
        dst_row = py * dst_stride
        for tx in range(target_w):
            px = dst_x + tx
            if not (0 <= px < dst_w):
                continue
            sx = (tx * src_w) // target_w
            s_off = src_row + sx * 3
            d_off = dst_row + px * 3
            dst[d_off : d_off + 3] = src_rgb[s_off : s_off + 3]


def render_poster_svg(draft: dict[str, Any], loaded_asset: LoadedAsset, workspace_name: str) -> bytes:
    """Render deterministic SVG poster embedding the verified asset and draft revision metadata."""
    version = int(draft["version"])
    rev_hash = str(draft["revision_hash"])
    short_hash = rev_hash[:12]
    b64_png = base64.b64encode(loaded_asset.raw_bytes).decode("ascii")

    title_lines = _wrap_text(draft["title"], max_chars=28, max_lines=2)
    headline_lines = _wrap_text(draft["headline"], max_chars=34, max_lines=2)
    caption_lines = _wrap_text(draft.get("caption") or "Draft promo siap ditinjau sebelum publikasi manual.", max_chars=48, max_lines=4)
    price_label = (draft.get("price_label") or "").strip()
    cta_text = (draft.get("cta_text") or "").strip()

    title_tspans = "".join(
        f'<tspan x="40" dy="{"0" if idx == 0 else "34"}">{_xml_text(line)}</tspan>'
        for idx, line in enumerate(title_lines)
    )
    headline_tspans = "".join(
        f'<tspan x="40" dy="{"0" if idx == 0 else "24"}">{_xml_text(line)}</tspan>'
        for idx, line in enumerate(headline_lines)
    )
    caption_tspans = "".join(
        f'<tspan x="40" dy="{"0" if idx == 0 else "22"}">{_xml_text(line)}</tspan>'
        for idx, line in enumerate(caption_lines)
    )

    price_block = ""
    if price_label:
        price_block = (
            '<rect x="40" y="544" width="248" height="44" rx="10" fill="#EFF6FF" stroke="#BFDBFE"/>'
            f'<text x="56" y="572" font-family="system-ui, sans-serif" font-size="20" font-weight="700" fill="#142B52">{_xml_text(price_label)}</text>'
        )
    cta_block = ""
    if cta_text:
        cta_x = 304 if price_label else 40
        cta_w = 296 if price_label else 560
        cta_block = (
            f'<rect x="{cta_x}" y="544" width="{cta_w}" height="44" rx="10" fill="#2563EB"/>'
            f'<text x="{cta_x + 18}" y="572" font-family="system-ui, sans-serif" font-size="16" font-weight="700" fill="#FFFFFF">{_xml_text(cta_text)}</text>'
        )

    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="640" height="800" viewBox="0 0 640 800" role="img" aria-label="{_xml_text(draft['title'])}">
  <metadata>
    <marketstudio:poster xmlns:marketstudio="https://marketstudio.local/ns/poster"
      draft_id="{_xml_text(draft['draft_id'])}"
      workspace_id="{_xml_text(draft['workspace_id'])}"
      version="{version}"
      revision_hash="{_xml_text(rev_hash)}"
      status="draft"
      asset_id="{_xml_text(loaded_asset.asset_id)}"
      asset_source="{_xml_text(loaded_asset.asset_source)}"
      asset_license="{_xml_text(loaded_asset.asset_license)}"
      asset_sha256="{_xml_text(loaded_asset.sha256)}" />
  </metadata>
  <rect width="640" height="800" fill="#F7F8FA"/>
  <rect x="20" y="20" width="600" height="760" rx="16" fill="#FFFFFF" stroke="#E2E6EC" stroke-width="2"/>
  <rect x="20" y="20" width="600" height="76" rx="16" fill="#142B52"/>
  <rect x="20" y="72" width="600" height="24" fill="#142B52"/>
  <text x="40" y="54" font-family="system-ui, sans-serif" font-size="18" font-weight="700" fill="#FFFFFF">{_xml_text(workspace_name[:34])}</text>
  <text x="40" y="78" font-family="system-ui, sans-serif" font-size="12" fill="#BFDBFE">MarketStudio Creative Studio · Status: DRAFT (Tidak Publish)</text>
  <rect x="478" y="38" width="122" height="32" rx="16" fill="#2563EB"/>
  <text x="539" y="59" text-anchor="middle" font-family="system-ui, sans-serif" font-size="13" font-weight="700" fill="#FFFFFF">DRAFT v{version}</text>
  <text x="40" y="138" font-family="system-ui, sans-serif" font-size="28" font-weight="800" fill="#142B52">{title_tspans}</text>
  <text x="40" y="212" font-family="system-ui, sans-serif" font-size="18" font-weight="600" fill="#2563EB">{headline_tspans}</text>
  <rect x="40" y="266" width="560" height="260" rx="12" fill="#F8FAFC" stroke="#CBD5E1" stroke-width="1.5"/>
  <image x="56" y="278" width="528" height="236" preserveAspectRatio="xMidYMid meet" href="data:image/png;base64,{b64_png}"/>
  {price_block}
  {cta_block}
  <text x="40" y="622" font-family="system-ui, sans-serif" font-size="15" fill="#172033">{caption_tspans}</text>
  <rect x="20" y="704" width="600" height="76" rx="16" fill="#F1F5F9"/>
  <rect x="20" y="704" width="600" height="20" fill="#F1F5F9"/>
  <line x1="20" y1="704" x2="620" y2="704" stroke="#E2E6EC" stroke-width="1.5"/>
  <text x="40" y="730" font-family="system-ui, sans-serif" font-size="12" font-weight="700" fill="#142B52">Sumber Aset: {_xml_text(loaded_asset.asset_source)} · Lisensi: {_xml_text(loaded_asset.asset_license)} ({_xml_text(loaded_asset.license_status)})</text>
  <text x="40" y="750" font-family="system-ui, sans-serif" font-size="11.5" fill="#475569">Atribusi: {_xml_text(loaded_asset.attribution_text)}</text>
  <text x="40" y="768" font-family="ui-monospace, monospace" font-size="11" fill="#526077">Draft {_xml_text(draft['draft_id'])} · v{version} · rev {short_hash} · status=draft (no publish)</text>
</svg>"""
    return svg.encode("utf-8")


def render_poster_png(draft: dict[str, Any], loaded_asset: LoadedAsset, workspace_name: str) -> bytes:
    """Render deterministic 640x800 PNG poster with verified asset image and tEXt provenance."""
    w, h = 640, 800
    buf = bytearray(bytes((247, 248, 250)) * (w * h))

    # Card & header/footer chrome
    _fill_rect(buf, w, h, 20, 20, 600, 760, (255, 255, 255))
    _stroke_rect(buf, w, h, 20, 20, 600, 760, 2, (226, 230, 236))
    _fill_rect(buf, w, h, 20, 20, 600, 76, (20, 43, 82))

    # Version badge in header
    version = int(draft["version"])
    rev_hash = str(draft["revision_hash"])
    _fill_rect(buf, w, h, 470, 38, 130, 34, (37, 99, 235))
    _draw_text_rgb(buf, w, h, 484, 48, f"DRAFT v{version}", 2, (255, 255, 255))

    # Header workspace title & draft-only subtitle
    _draw_text_rgb(buf, w, h, 40, 38, workspace_name[:30], 2, (255, 255, 255))
    _draw_text_rgb(buf, w, h, 40, 64, "MarketStudio Creative Studio | DRAFT ONLY (No Publish)", 1, (191, 219, 254))

    # Title & headline
    title_lines = _wrap_text(draft["title"], max_chars=28, max_lines=2)
    for idx, line in enumerate(title_lines):
        _draw_text_rgb(buf, w, h, 40, 118 + idx * 28, line, 3, (20, 43, 82))

    headline_lines = _wrap_text(draft["headline"], max_chars=44, max_lines=2)
    for idx, line in enumerate(headline_lines):
        _draw_text_rgb(buf, w, h, 40, 192 + idx * 22, line, 2, (37, 99, 235))

    # Image frame & composited verified RGB asset
    _fill_rect(buf, w, h, 40, 258, 560, 260, (248, 250, 252))
    _stroke_rect(buf, w, h, 40, 258, 560, 260, 2, (203, 213, 225))
    scale = min(536 / max(1, loaded_asset.width), 236 / max(1, loaded_asset.height))
    draw_w = max(1, int(round(loaded_asset.width * scale)))
    draw_h = max(1, int(round(loaded_asset.height * scale)))
    draw_x = 40 + (560 - draw_w) // 2
    draw_y = 258 + (260 - draw_h) // 2
    _blit_scaled_rgb(
        buf,
        w,
        h,
        draw_x,
        draw_y,
        draw_w,
        draw_h,
        loaded_asset.rgb_bytes,
        loaded_asset.width,
        loaded_asset.height,
    )

    # Price badge and CTA pill
    price_label = (draft.get("price_label") or "").strip()
    cta_text = (draft.get("cta_text") or "").strip()
    if price_label:
        _fill_rect(buf, w, h, 40, 536, 250, 44, (239, 246, 255))
        _stroke_rect(buf, w, h, 40, 536, 250, 44, 1, (191, 219, 254))
        _draw_text_rgb(buf, w, h, 54, 551, price_label[:18], 2, (20, 43, 82))
    if cta_text:
        cta_x = 304 if price_label else 40
        cta_w = 296 if price_label else 560
        _fill_rect(buf, w, h, cta_x, 536, cta_w, 44, (37, 99, 235))
        _draw_text_rgb(buf, w, h, cta_x + 16, 551, cta_text[:22], 2, (255, 255, 255))

    # Caption lines
    caption_lines = _wrap_text(
        draft.get("caption") or "Draft promo siap ditinjau sebelum publikasi manual.",
        max_chars=44,
        max_lines=4,
    )
    for idx, line in enumerate(caption_lines):
        _draw_text_rgb(buf, w, h, 40, 602 + idx * 22, line, 2, (23, 32, 51))

    # Footer with asset attribution & draft version lock info
    _fill_rect(buf, w, h, 20, 704, 600, 76, (241, 245, 249))
    _fill_rect(buf, w, h, 20, 704, 600, 2, (226, 230, 236))
    _draw_text_rgb(
        buf,
        w,
        h,
        40,
        718,
        f"Sumber: {loaded_asset.asset_source} | Lisensi: {loaded_asset.asset_license} ({loaded_asset.license_status})",
        1,
        (20, 43, 82),
    )
    _draw_text_rgb(buf, w, h, 40, 738, f"Atribusi: {loaded_asset.attribution_text[:72]}", 1, (71, 85, 105))
    _draw_text_rgb(
        buf,
        w,
        h,
        40,
        756,
        f"Draft {draft['draft_id']} | v{version} | rev {rev_hash[:12]} | status=draft (no publish)",
        1,
        (82, 96, 119),
    )

    text_chunks = {
        "Title": str(draft["title"]),
        "Software": "MarketStudio Creative Studio Baseline",
        "DraftId": str(draft["draft_id"]),
        "DraftVersion": str(version),
        "DraftRevisionHash": rev_hash,
        "DraftStatus": "draft",
        "AssetId": loaded_asset.asset_id,
        "AssetSource": loaded_asset.asset_source,
        "AssetLicense": loaded_asset.asset_license,
        "AssetAttribution": loaded_asset.attribution_text,
        "AssetSha256": loaded_asset.sha256,
    }
    return encode_png_rgb(w, h, bytes(buf), text_chunks=text_chunks)


def render_poster_artifact(
    draft: dict[str, Any],
    loaded_asset: LoadedAsset,
    workspace_name: str,
    fmt: str,
) -> tuple[bytes, str, str, str]:
    """Render poster bytes in requested format ('svg' or 'png') and compute SHA-256."""
    norm_fmt = fmt.lower().strip()
    if norm_fmt == "svg":
        content = render_poster_svg(draft, loaded_asset, workspace_name)
        content_type = "image/svg+xml; charset=utf-8"
        ext = "svg"
    elif norm_fmt == "png":
        content = render_poster_png(draft, loaded_asset, workspace_name)
        content_type = "image/png"
        ext = "png"
    else:
        raise DomainError(422, "unsupported_export_format", f"Format '{fmt}' tidak didukung.")

    filename = _safe_filename(f"marketstudio-poster-{draft['draft_id']}-v{int(draft['version'])}.{ext}")
    sha256_hex = hashlib.sha256(content).hexdigest()
    return content, content_type, filename, sha256_hex
