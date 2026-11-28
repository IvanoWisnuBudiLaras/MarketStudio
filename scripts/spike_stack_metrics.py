#!/usr/bin/env python3
"""Spike benchmark script measuring in-process server/SQLite initialization time, latency, memory RSS, and database size for MarketStudio alur #1."""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db import DatabaseConfig, resolve_db_config
from app.server import create_server


def get_current_rss_kb() -> float:
    """Read current resident set size (RSS) in kilobytes from /proc/self/status or resource."""
    status_path = Path("/proc/self/status")
    if status_path.is_file():
        try:
            for line in status_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return float(parts[1])
        except Exception:
            pass
    # Fallback to getrusage (ru_maxrss is in KB on Linux)
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def get_peak_rss_kb() -> float:
    """Get peak resident set size in kilobytes."""
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _http_request(
    base_url: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    token: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[float, int, dict[str, Any]]:
    """Execute single HTTP request and return (latency_ms, status_code, parsed_json)."""
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    if token:
        req_headers["Authorization"] = f"Bearer {token}"
    if idempotency_key:
        req_headers["Idempotency-Key"] = idempotency_key

    data = json.dumps(body).encode("utf-8") if body is not None else None
    url = f"{base_url}{path}"
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
            payload = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        status = exc.code
        payload = json.loads(raw) if raw else {}
        exc.close()
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return latency_ms, status, payload


def run_spike(
    db_path: str | Path | None = None,
    iterations: int = 1,
    quiet: bool = False,
    host: str = "127.0.0.1",
    port: int = 0,
    verbose_logs: bool = False,
) -> dict[str, Any]:
    """Execute reproducible spike benchmark for MarketStudio alur #1 with strict SQLite isolation."""
    if iterations < 1:
        raise ValueError("iterations must be at least 1")

    if not verbose_logs:
        os.environ["MARKETSTUDIO_QUIET_LOGS"] = "1"

    temp_dir: tempfile.TemporaryDirectory | None = None
    if db_path is None:
        temp_dir = tempfile.TemporaryDirectory(prefix="marketstudio_spike_")
        target_db = Path(temp_dir.name) / "spike_marketstudio.db"
    else:
        target_db = Path(db_path).resolve()
        if target_db.exists():
            raise ValueError(
                f"File database '{target_db}' sudah ada. "
                "Spike benchmark alur #1 hanya menerima path file baru untuk menjamin isolasi data tanpa memutasi data existing."
            )
        target_db.parent.mkdir(parents=True, exist_ok=True)

    target_db_str = str(target_db)

    # Force explicit SQLite backend isolation against any PostgreSQL ambient environment
    prev_backend = os.environ.get("MARKETSTUDIO_DB_BACKEND")
    prev_db_url = os.environ.get("DATABASE_URL")
    prev_ms_db_url = os.environ.get("MARKETSTUDIO_DATABASE_URL")
    os.environ["MARKETSTUDIO_DB_BACKEND"] = "sqlite"
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("MARKETSTUDIO_DATABASE_URL", None)

    # Construct explicit SQLite configuration object
    db_config = DatabaseConfig(
        backend="sqlite",
        target=target_db_str,
        auto_migrate=True,
    )

    # 1. In-process Server & SQLite Initialization Measurement
    t_start0 = time.perf_counter()
    server = create_server(
        host=host,
        port=port,
        db_path=db_config,
        backend="sqlite",
        database_url=None,
    )
    startup_inprocess_ms = (time.perf_counter() - t_start0) * 1000.0

    actual_port = server.server_address[1]
    base_url = f"http://{host}:{actual_port}"
    idle_rss_kb = get_current_rss_kb()

    # Start server in daemon thread
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    results: dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "database_backend": "sqlite",
        "database_path": target_db_str,
        "startup_inprocess_ms": round(startup_inprocess_ms, 2),
        "cold_startup_ms": round(startup_inprocess_ms, 2),  # backward compatibility alias
        "idle_rss_mb": round(idle_rss_kb / 1024.0, 2),
        "iterations": iterations,
        "step_latencies_ms": {},
        "summary": {},
    }

    step_measurements: dict[str, list[float]] = {
        "post_sessions": [],
        "post_workspaces": [],
        "post_offerings_goods": [],
        "post_offerings_service": [],
        "post_purchases": [],
        "post_sales": [],
        "get_daily_report": [],
    }

    try:
        # Run iterations
        for it in range(1, iterations + 1):
            # Step 1: Login
            lat_login, status_login, res_login = _http_request(
                base_url,
                "POST",
                "/v1/sessions",
                body={"actor_id": "actor_a", "passcode": "dev-a-pass"},
            )
            if status_login != 201:
                raise RuntimeError(f"Login failed (status {status_login}): {res_login}")
            token = res_login["item"]["token"]
            step_measurements["post_sessions"].append(lat_login)

            # Step 2: Create Workspace
            ws_name = f"Spike Workspace {it}"
            lat_ws, status_ws, res_ws = _http_request(
                base_url,
                "POST",
                "/v1/workspaces",
                body={"name": ws_name},
                token=token,
            )
            if status_ws != 201:
                raise RuntimeError(f"Create workspace failed (status {status_ws}): {res_ws}")
            ws_id = res_ws["item"]["workspace_id"]
            step_measurements["post_workspaces"].append(lat_ws)

            # Step 3: Create Goods Offering
            lat_off_g, status_off_g, res_off_g = _http_request(
                base_url,
                "POST",
                f"/v1/workspaces/{ws_id}/offerings",
                body={
                    "name": f"Bakso Sapi Spesial Iter {it}",
                    "offering_type": "goods",
                    "unit_price_idr": 20000,
                    "unit": "porsi",
                },
                token=token,
            )
            if status_off_g != 201:
                raise RuntimeError(f"Create goods offering failed (status {status_off_g}): {res_off_g}")
            off_goods_id = res_off_g["item"]["offering_id"]
            step_measurements["post_offerings_goods"].append(lat_off_g)

            # Step 4: Create Service Offering
            lat_off_s, status_off_s, res_off_s = _http_request(
                base_url,
                "POST",
                f"/v1/workspaces/{ws_id}/offerings",
                body={
                    "name": f"Layanan Antar Catering Iter {it}",
                    "offering_type": "service",
                    "unit_price_idr": 15000,
                    "unit": "trip",
                },
                token=token,
            )
            if status_off_s != 201:
                raise RuntimeError(f"Create service offering failed (status {status_off_s}): {res_off_s}")
            off_svc_id = res_off_s["item"]["offering_id"]
            step_measurements["post_offerings_service"].append(lat_off_s)

            # Step 5: Purchase Goods
            lat_purch, status_purch, res_purch = _http_request(
                base_url,
                "POST",
                f"/v1/workspaces/{ws_id}/purchases",
                body={
                    "offering_id": off_goods_id,
                    "qty": "50",
                    "total_cost_idr": 500000,
                    "occurred_at": "2026-11-28T09:00:00+07:00",
                },
                token=token,
                idempotency_key=f"spike-purch-iter-{it}",
            )
            if status_purch != 201:
                raise RuntimeError(f"Purchase failed (status {status_purch}): {res_purch}")
            step_measurements["post_purchases"].append(lat_purch)

            # Step 6: Sale Goods + Service
            lat_sale, status_sale, res_sale = _http_request(
                base_url,
                "POST",
                f"/v1/workspaces/{ws_id}/sales",
                body={
                    "lines": [
                        {"offering_id": off_goods_id, "qty": "2", "total_price_idr": 40000},
                        {"offering_id": off_svc_id, "qty": "1", "total_price_idr": 15000},
                    ],
                    "occurred_at": "2026-11-28T10:00:00+07:00",
                },
                token=token,
                idempotency_key=f"spike-sale-iter-{it}",
            )
            if status_sale != 201:
                raise RuntimeError(f"Sale failed (status {status_sale}): {res_sale}")
            step_measurements["post_sales"].append(lat_sale)

            # Step 7: Daily Report
            lat_rep, status_rep, res_rep = _http_request(
                base_url,
                "GET",
                f"/v1/workspaces/{ws_id}/reports/daily?date=2026-11-28",
                token=token,
            )
            if status_rep != 200:
                raise RuntimeError(f"Daily report failed (status {status_rep}): {res_rep}")
            step_measurements["get_daily_report"].append(lat_rep)

        loaded_rss_kb = get_current_rss_kb()
        peak_rss_kb = max(get_peak_rss_kb(), loaded_rss_kb)
        db_size_kb = target_db.stat().st_size / 1024.0 if target_db.exists() else 0.0

        step_stats: dict[str, dict[str, float]] = {}
        total_mean_latency = 0.0
        for step, lats in step_measurements.items():
            mean_lat = sum(lats) / len(lats)
            min_lat = min(lats)
            max_lat = max(lats)
            total_mean_latency += mean_lat
            step_stats[step] = {
                "mean_ms": round(mean_lat, 2),
                "min_ms": round(min_lat, 2),
                "max_ms": round(max_lat, 2),
            }

        results["step_latencies_ms"] = step_stats
        results["loaded_rss_mb"] = round(loaded_rss_kb / 1024.0, 2)
        results["peak_rss_mb"] = round(peak_rss_kb / 1024.0, 2)
        results["database_size_kb"] = round(db_size_kb, 2)
        results["summary"] = {
            "total_flow_latency_mean_ms": round(total_mean_latency, 2),
            "startup_inprocess_ms": round(startup_inprocess_ms, 2),
            "cold_startup_ms": round(startup_inprocess_ms, 2),
            "idle_rss_mb": round(idle_rss_kb / 1024.0, 2),
            "loaded_rss_mb": round(loaded_rss_kb / 1024.0, 2),
            "database_size_kb": round(db_size_kb, 2),
        }

    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2.0)
        if temp_dir is not None:
            temp_dir.cleanup()
        # Restore ambient environment variables
        if prev_backend is not None:
            os.environ["MARKETSTUDIO_DB_BACKEND"] = prev_backend
        else:
            os.environ.pop("MARKETSTUDIO_DB_BACKEND", None)
        if prev_db_url is not None:
            os.environ["DATABASE_URL"] = prev_db_url
        if prev_ms_db_url is not None:
            os.environ["MARKETSTUDIO_DATABASE_URL"] = prev_ms_db_url

    if not quiet:
        _print_report(results)

    return results


def _print_report(results: dict[str, Any]) -> None:
    """Print readable text report to stdout."""
    print("=" * 68)
    print("MarketStudio MVP Stack Benchmark Spike — Alur #1")
    print("=" * 68)
    print(f"Timestamp (UTC)           : {results['timestamp_utc']}")
    print(f"Python Runtime            : {results['python_version']} ({results['platform']})")
    print(f"Database Backend          : {results['database_backend']}")
    print(f"Iterations                : {results['iterations']}")
    print("-" * 68)
    print(f"In-process Init Time      : {results['startup_inprocess_ms']} ms (server + SQLite)")
    print(f"Idle Memory RSS           : {results['idle_rss_mb']} MB")
    print(f"Loaded Memory RSS         : {results['loaded_rss_mb']} MB (Peak: {results['peak_rss_mb']} MB)")
    print(f"Database File Size        : {results['database_size_kb']} KB")
    print("-" * 68)
    print("Per-Request Latency Breakdown (Alur #1):")
    print(f"  {'Step':<28} | {'Mean (ms)':<10} | {'Min (ms)':<10} | {'Max (ms)':<10}")
    print("  " + "-" * 62)
    for step, metrics in results["step_latencies_ms"].items():
        print(f"  {step:<28} | {metrics['mean_ms']:<10.2f} | {metrics['min_ms']:<10.2f} | {metrics['max_ms']:<10.2f}")
    print("-" * 68)
    print(f"Total Flow Mean Latency   : {results['summary']['total_flow_latency_mean_ms']} ms")
    print("=" * 68)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark and verify MarketStudio MVP stack metrics (in-process init, latency, memory RSS, disk size)."
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to new SQLite database file (rejects existing files). Defaults to an isolated temporary file.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="Number of full flow iterations to execute and average (default: 3).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output raw JSON benchmark metrics.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress textual output (except JSON if requested).",
    )
    parser.add_argument(
        "--verbose-logs",
        action="store_true",
        help="Keep HTTP server request logs on stdout.",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address to bind server (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port to bind server (default: 0 for dynamic ephemeral port).",
    )

    args = parser.parse_args()

    quiet = args.quiet or args.json_output
    try:
        data = run_spike(
            db_path=args.db_path,
            iterations=args.iterations,
            quiet=quiet,
            host=args.host,
            port=args.port,
            verbose_logs=args.verbose_logs,
        )
        if args.json_output:
            print(json.dumps(data, indent=2))
        return 0
    except ValueError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2
    except Exception as exc:
        sys.stderr.write(f"ERROR: Spike execution failed: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
