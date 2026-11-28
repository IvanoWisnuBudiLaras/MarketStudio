"""Provider boundary for synthetic Creative Studio image briefs."""

from __future__ import annotations

import json
import os
import queue
import struct
import threading
import time
import urllib.request
import zlib
from typing import Protocol
from urllib.parse import urlsplit

from app.creative import decode_png_rgb, encode_png_rgb
from app.domain import DomainError

MAX_PNG_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 15
_PROVIDER_SLOTS = threading.BoundedSemaphore(4)
SUBJECTS = {"goods": "generic product", "service": "generic service", "hybrid": "generic product and service"}
STYLES = {"studio": "clean studio lighting", "illustration": "warm editorial illustration"}


def synthetic_prompt(offering_type: str, style: str) -> str:
    return (
        f"Create a 3:2 landscape poster image for a fictional {SUBJECTS[offering_type]}. "
        f"Use {STYLES[style]}. No text, logos, or recognizable real people."
    )


class ImageProvider(Protocol):
    name: str

    def generate(self, prompt: str) -> bytes: ...


def provider_error(code: str = "image_provider_failed") -> DomainError:
    message = {
        "image_provider_timeout": "Penyedia gambar melewati batas waktu.",
        "image_provider_unavailable": "Penyedia gambar belum tersedia.",
        "image_output_invalid": "Hasil gambar harus berupa PNG RGB/RGBA dengan rasio 3:2 dan resolusi 600×400 hingga 1536×1024.",
    }.get(code, "Penyedia gambar gagal menghasilkan gambar.")
    return DomainError(503, code, message)


class StubImageProvider:
    name = "stub_test"

    def __init__(self, mode: str) -> None:
        self.mode = mode

    def generate(self, prompt: str) -> bytes:
        if self.mode == "timeout":
            raise provider_error("image_provider_timeout")
        if self.mode == "failure":
            raise provider_error()
        if self.mode == "slow":
            time.sleep(1)
        color = (246, 178, 125) if "illustration" in prompt else (147, 197, 253)
        row = bytes(color) * 300 + bytes((30, 64, 110)) * 300
        return encode_png_rgb(600, 400, row * 400)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class HttpsImageProvider:
    name = "approved_https_gateway"

    def __init__(self, url: str, token: str) -> None:
        self.url = url
        self.token = token

    def __repr__(self) -> str:
        return f"HttpsImageProvider(url={self.url!r}, token='***')"

    def generate(self, prompt: str) -> bytes:
        if not _PROVIDER_SLOTS.acquire(blocking=False):
            raise provider_error("image_provider_unavailable")
        result: queue.Queue[bytes | DomainError] = queue.Queue(maxsize=1)

        def fetch() -> None:
            try:
                result.put(self._request_png(prompt))
            except DomainError as exc:
                result.put(exc)
            except Exception:
                result.put(provider_error())
            finally:
                _PROVIDER_SLOTS.release()

        worker = threading.Thread(target=fetch, daemon=True)
        try:
            worker.start()
        except RuntimeError:
            _PROVIDER_SLOTS.release()
            raise provider_error() from None
        try:
            output = result.get(timeout=TIMEOUT_SECONDS)
        except queue.Empty:
            raise provider_error("image_provider_timeout") from None
        if isinstance(output, DomainError):
            raise output
        return output

    def _request_png(self, prompt: str) -> bytes:
        request = urllib.request.Request(
            self.url,
            method="POST",
            data=json.dumps({"prompt": prompt, "width": 1200, "height": 800}).encode(),
            headers={"Content-Type": "application/json", "Accept": "image/png",
                     "Authorization": f"Bearer {self.token}"},
        )
        deadline = time.monotonic() + TIMEOUT_SECONDS
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=TIMEOUT_SECONDS) as response:
                if response.headers.get_content_type() != "image/png":
                    raise provider_error("image_output_invalid")
                result = bytearray()
                while len(result) <= MAX_PNG_BYTES:
                    if time.monotonic() >= deadline:
                        raise TimeoutError
                    read_fn = getattr(response, "read1", None) or getattr(response, "read", None)
                    chunk = read_fn(min(65536, MAX_PNG_BYTES + 1 - len(result))) if read_fn else b""
                    if not chunk:
                        return bytes(result)
                    result.extend(chunk)
        except TimeoutError:
            raise provider_error("image_provider_timeout") from None
        except (OSError, ValueError) as exc:
            if isinstance(getattr(exc, "reason", None), TimeoutError):
                raise provider_error("image_provider_timeout") from None
            raise provider_error() from None
        raise provider_error("image_output_invalid")


def configured_provider() -> ImageProvider:
    mode = os.getenv("MARKETSTUDIO_AI_IMAGE_STUB")
    if os.getenv("MARKETSTUDIO_ENV") == "development" and mode in {"valid", "failure", "timeout", "slow"}:
        return StubImageProvider(mode)

    url = os.getenv("MARKETSTUDIO_AI_IMAGE_URL", "")
    token = os.getenv("MARKETSTUDIO_AI_IMAGE_TOKEN", "")
    try:
        endpoint = urlsplit(url)
        if (os.getenv("MARKETSTUDIO_AI_IMAGE_APPROVED") == "1" and token
                and endpoint.scheme == "https" and endpoint.hostname and not endpoint.username
                and not endpoint.password and not endpoint.fragment and not endpoint.query):
            return HttpsImageProvider(url, token)
    except ValueError:
        pass
    raise provider_error("image_provider_unavailable")


def normalize_image(raw: bytes) -> tuple[bytes, int, int]:
    """Validate bounded dimensions before decoding, then strip provider PNG metadata."""
    try:
        if not isinstance(raw, bytes) or not 33 <= len(raw) <= MAX_PNG_BYTES:
            raise ValueError
        width, height = struct.unpack_from(">II", raw, 16)
        if raw[12:16] != b"IHDR" or not 400 <= height <= 1024 or width * 2 != height * 3:
            raise ValueError
        width, height, pixels = decode_png_rgb(raw)
        png = encode_png_rgb(width, height, pixels)
    except (ValueError, struct.error, zlib.error):
        raise provider_error("image_output_invalid") from None
    return png, width, height
