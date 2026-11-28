#!/usr/bin/env python3
"""MarketStudio release web endpoint smoke check tool (Issue #43).

Verifies the release web application endpoints (root HTML and /health JSON)
using only Python 3 standard library.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, NamedTuple


class CheckResult(NamedTuple):
    name: str
    url: str
    success: bool
    status_code: int | None
    message: str
    duration_ms: float
    details: dict[str, Any]


def normalize_base_url(raw_url: str) -> str:
    """Validate and normalize a target base URL."""
    clean = raw_url.strip()
    parsed = urllib.parse.urlparse(clean)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(
            f"Base URL tidak valid '{clean}'. Skema harus http:// atau https:// dengan host valid."
        )
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def check_root(base_url: str, timeout: float = 10.0) -> CheckResult:
    """Check GET / root entrypoint returns 200 OK with valid HTML content."""
    url = f"{base_url}/"
    headers = {
        "User-Agent": "MarketStudio-SmokeCheck/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    start = time.perf_counter()

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            raw_body = resp.read(1048576)  # max 1MB
            body_text = raw_body.decode("utf-8", errors="replace")

            if status != 200:
                return CheckResult(
                    name="root",
                    url=url,
                    success=False,
                    status_code=status,
                    message=f"HTTP non-200 pada halaman utama: HTTP {status}",
                    duration_ms=elapsed_ms,
                    details={"content_type": content_type, "body_bytes": len(raw_body)},
                )

            if len(raw_body) == 0:
                return CheckResult(
                    name="root",
                    url=url,
                    success=False,
                    status_code=status,
                    message="Respons halaman utama kosong (0 bytes)",
                    duration_ms=elapsed_ms,
                    details={"content_type": content_type, "body_bytes": 0},
                )

            # Valid web content criteria: HTML doctype or HTML tag or MarketStudio title/content
            lower_body = body_text.lower()
            has_html_marker = (
                "<!doctype html" in lower_body
                or "<html" in lower_body
                or "marketstudio" in lower_body
            )
            if not has_html_marker:
                return CheckResult(
                    name="root",
                    url=url,
                    success=False,
                    status_code=status,
                    message="Konten respons halaman utama tidak memuat marker HTML atau MarketStudio yang valid",
                    duration_ms=elapsed_ms,
                    details={"content_type": content_type, "body_bytes": len(raw_body)},
                )

            return CheckResult(
                name="root",
                url=url,
                success=True,
                status_code=status,
                message=f"HTTP {status} OK (HTML valid, {len(raw_body)} bytes)",
                duration_ms=elapsed_ms,
                details={
                    "content_type": content_type,
                    "body_bytes": len(raw_body),
                    "has_marker": True,
                },
            )

    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        try:
            body_excerpt = exc.read(256).decode("utf-8", errors="replace").strip()
        except Exception:
            body_excerpt = ""
        finally:
            exc.close()
        desc = f": {body_excerpt}" if body_excerpt else ""
        return CheckResult(
            name="root",
            url=url,
            success=False,
            status_code=exc.code,
            message=f"HTTP {exc.code} ({exc.reason}){desc}",
            duration_ms=elapsed_ms,
            details={"error": "HTTPError", "code": exc.code, "reason": str(exc.reason)},
        )

    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        msg = _format_network_error(exc, timeout)
        return CheckResult(
            name="root",
            url=url,
            success=False,
            status_code=None,
            message=msg,
            duration_ms=elapsed_ms,
            details={"error": type(exc).__name__, "reason": str(exc)},
        )

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return CheckResult(
            name="root",
            url=url,
            success=False,
            status_code=None,
            message=f"Kesalahan tak terduga: {type(exc).__name__}: {exc}",
            duration_ms=elapsed_ms,
            details={"error": type(exc).__name__, "reason": str(exc)},
        )


def check_health(base_url: str, timeout: float = 10.0) -> CheckResult:
    """Check GET /health endpoint returns 200 OK with JSON {'status': 'ok'}."""
    url = f"{base_url}/health"
    headers = {
        "User-Agent": "MarketStudio-SmokeCheck/1.0",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    start = time.perf_counter()

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            raw_body = resp.read(1048576)  # max 1MB
            body_text = raw_body.decode("utf-8", errors="replace")

            if status != 200:
                return CheckResult(
                    name="health",
                    url=url,
                    success=False,
                    status_code=status,
                    message=f"HTTP non-200 pada /health: HTTP {status}",
                    duration_ms=elapsed_ms,
                    details={"content_type": content_type, "body_bytes": len(raw_body)},
                )

            try:
                data = json.loads(body_text)
            except (json.JSONDecodeError, ValueError) as exc:
                excerpt = body_text[:120].strip()
                return CheckResult(
                    name="health",
                    url=url,
                    success=False,
                    status_code=status,
                    message=f"Respons /health bukan format JSON valid: {exc} (snippet: '{excerpt}')",
                    duration_ms=elapsed_ms,
                    details={"content_type": content_type, "raw_snippet": excerpt},
                )

            if not isinstance(data, dict):
                return CheckResult(
                    name="health",
                    url=url,
                    success=False,
                    status_code=status,
                    message=f"Respons /health bukan JSON object (tipe: {type(data).__name__})",
                    duration_ms=elapsed_ms,
                    details={"json_type": type(data).__name__},
                )

            health_status = data.get("status")
            if health_status != "ok":
                return CheckResult(
                    name="health",
                    url=url,
                    success=False,
                    status_code=status,
                    message=f"Status /health bukan 'ok' (diterima: {health_status!r})",
                    duration_ms=elapsed_ms,
                    details={"payload": data},
                )

            service_name = data.get("service", "unknown")
            backend = data.get("db_backend", "unknown")
            return CheckResult(
                name="health",
                url=url,
                success=True,
                status_code=status,
                message=f"HTTP {status} OK (status: ok, service: {service_name}, backend: {backend})",
                duration_ms=elapsed_ms,
                details={"payload": data},
            )

    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        try:
            body_excerpt = exc.read(256).decode("utf-8", errors="replace").strip()
        except Exception:
            body_excerpt = ""
        finally:
            exc.close()
        desc = f": {body_excerpt}" if body_excerpt else ""
        return CheckResult(
            name="health",
            url=url,
            success=False,
            status_code=exc.code,
            message=f"HTTP {exc.code} ({exc.reason}){desc}",
            duration_ms=elapsed_ms,
            details={"error": "HTTPError", "code": exc.code, "reason": str(exc.reason)},
        )

    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        msg = _format_network_error(exc, timeout)
        return CheckResult(
            name="health",
            url=url,
            success=False,
            status_code=None,
            message=msg,
            duration_ms=elapsed_ms,
            details={"error": type(exc).__name__, "reason": str(exc)},
        )

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return CheckResult(
            name="health",
            url=url,
            success=False,
            status_code=None,
            message=f"Kesalahan tak terduga: {type(exc).__name__}: {exc}",
            duration_ms=elapsed_ms,
            details={"error": type(exc).__name__, "reason": str(exc)},
        )


def _format_network_error(exc: BaseException, timeout: float) -> str:
    """Produce descriptive, readable message for network failures."""
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return f"Permintaan melebihi batas waktu (timeout {timeout:.1f} detik)"

    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return f"Permintaan melebihi batas waktu (timeout {timeout:.1f} detik)"
        reason_str = str(reason).lower()
        if "timed out" in reason_str:
            return f"Permintaan melebihi batas waktu (timeout {timeout:.1f} detik): {reason}"
        if isinstance(reason, ConnectionRefusedError) or "connection refused" in reason_str:
            return f"Koneksi ditolak (Connection refused) - server web target tidak aktif atau port salah: {reason}"
        if isinstance(reason, socket.gaierror) or "name or service not known" in reason_str:
            return f"Host tidak ditemukan (DNS resolution failed): {reason}"
        return f"Kegagalan koneksi jaringan (URLError): {reason}"

    return f"Kegagalan jaringan: {type(exc).__name__}: {exc}"


def run_smoke_check(base_url: str, timeout: float = 10.0) -> tuple[bool, list[CheckResult]]:
    """Execute all release smoke checks sequentially.

    Returns (all_passed, results).
    """
    normalized_url = normalize_base_url(base_url)
    results = [
        check_root(normalized_url, timeout=timeout),
        check_health(normalized_url, timeout=timeout),
    ]
    all_passed = all(r.success for r in results)
    return all_passed, results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MarketStudio release web endpoint smoke check tool (Issue #43)."
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=None,
        help="Target base URL (contoh: http://127.0.0.1:8000). Dapat juga diset via MARKETSTUDIO_BASE_URL.",
    )
    parser.add_argument(
        "--base-url",
        "--url",
        "-u",
        dest="base_url",
        default=None,
        help="Target base URL (alias untuk argumen url).",
    )
    parser.add_argument(
        "--timeout",
        "-t",
        type=float,
        default=None,
        help="Timeout HTTP request dalam detik (default: 10.0 atau MARKETSTUDIO_SMOKE_TIMEOUT).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Cetak output dalam format JSON terstruktur.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Mode senyap: sembunyikan output detail, hanya cetak ringkasan akhir.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # 1. Resolve base URL
    raw_url = (
        args.base_url
        or args.url
        or os.environ.get("MARKETSTUDIO_BASE_URL")
        or os.environ.get("BASE_URL")
    )
    if not raw_url:
        print(
            "Error: Target base URL tidak ditentukan.\n"
            "Gunakan: python3 scripts/smoke_check.py <URL> [opsi]\n"
            "Atau set environment variable MARKETSTUDIO_BASE_URL.",
            file=sys.stderr,
        )
        return 2

    try:
        base_url = normalize_base_url(raw_url)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    # 2. Resolve timeout
    if args.timeout is not None:
        timeout = args.timeout
    else:
        env_timeout = os.environ.get("MARKETSTUDIO_SMOKE_TIMEOUT") or os.environ.get("SMOKE_TIMEOUT")
        if env_timeout:
            try:
                timeout = float(env_timeout)
            except ValueError:
                print(
                    f"Error: Format timeout dari environment variable tidak valid: '{env_timeout}'",
                    file=sys.stderr,
                )
                return 2
        else:
            timeout = 10.0

    if timeout <= 0:
        print(
            f"Error: Nilai timeout harus positif (> 0 detik), diberikan: {timeout}",
            file=sys.stderr,
        )
        return 2

    # 3. Execute smoke checks
    if not args.quiet and not args.json:
        print(f"=== Menjalankan MarketStudio Smoke Check ===")
        print(f"Target Base URL : {base_url}")
        print(f"Timeout         : {timeout:.1f}s")
        print("---------------------------------------------")

    all_passed, results = run_smoke_check(base_url, timeout=timeout)

    # 4. Format and print output
    if args.json:
        payload = {
            "base_url": base_url,
            "timeout_seconds": timeout,
            "all_passed": all_passed,
            "total_checks": len(results),
            "passed_checks": sum(1 for r in results if r.success),
            "failed_checks": sum(1 for r in results if not r.success),
            "checks": [
                {
                    "name": r.name,
                    "url": r.url,
                    "success": r.success,
                    "status_code": r.status_code,
                    "message": r.message,
                    "duration_ms": round(r.duration_ms, 2),
                    "details": r.details,
                }
                for r in results
            ],
        }
        print(json.dumps(payload, indent=2))
    else:
        for r in results:
            tag = "[PASS]" if r.success else "[FAIL]"
            if not args.quiet or not r.success:
                print(f"{tag} {r.name.upper()} ({r.url}) [{r.duration_ms:.1f}ms] -> {r.message}")

        if all_passed:
            print(f"\nPASS Smoke check berhasil: {len(results)}/{len(results)} endpoint sehat.")
        else:
            failed_count = sum(1 for r in results if not r.success)
            print(
                f"\nFAIL Smoke check gagal: {failed_count}/{len(results)} endpoint bermasalah.",
                file=sys.stderr,
            )

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
