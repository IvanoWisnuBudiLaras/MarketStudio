"""Automated tests for MarketStudio release web endpoint smoke check tool (Issue #43)."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.server import create_server
from scripts.smoke_check import (
    CheckResult,
    check_health,
    check_root,
    normalize_base_url,
    run_smoke_check,
)


class SmokeCheckRealServerTest(unittest.TestCase):
    """Test smoke check against a real MarketStudio baseline server."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "smoke_real.db")
        self.server = create_server(host="127.0.0.1", port=0, db_path=self.db_path)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmpdir.cleanup()

    def test_smoke_check_success_library_calls(self) -> None:
        root_res = check_root(self.base_url, timeout=5.0)
        self.assertTrue(root_res.success)
        self.assertEqual(root_res.status_code, 200)
        self.assertIn("HTML valid", root_res.message)
        self.assertGreater(root_res.details["body_bytes"], 0)

        health_res = check_health(self.base_url, timeout=5.0)
        self.assertTrue(health_res.success)
        self.assertEqual(health_res.status_code, 200)
        self.assertIn("status: ok", health_res.message)
        self.assertEqual(health_res.details["payload"]["status"], "ok")

        all_passed, results = run_smoke_check(self.base_url, timeout=5.0)
        self.assertTrue(all_passed)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.success for r in results))

    def test_smoke_check_cli_positional_and_flag(self) -> None:
        script_path = str(Path(__file__).resolve().parents[1] / "scripts" / "smoke_check.py")

        # 1. Positional URL
        proc = subprocess.run(
            [sys.executable, script_path, self.base_url, "--timeout", "5.0"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, f"STDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
        self.assertIn("PASS Smoke check berhasil: 2/2 endpoint sehat", proc.stdout)
        self.assertIn("[PASS] ROOT", proc.stdout)
        self.assertIn("[PASS] HEALTH", proc.stdout)

        # 2. Flag --base-url
        proc_flag = subprocess.run(
            [sys.executable, script_path, "--base-url", self.base_url, "-t", "5.0"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc_flag.returncode, 0)
        self.assertIn("PASS Smoke check berhasil", proc_flag.stdout)

        # 3. Environment variable fallback
        env = dict(os.environ, MARKETSTUDIO_BASE_URL=self.base_url, MARKETSTUDIO_SMOKE_TIMEOUT="5.0")
        proc_env = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(proc_env.returncode, 0)
        self.assertIn("PASS Smoke check berhasil", proc_env.stdout)

    def test_smoke_check_cli_json_and_quiet_modes(self) -> None:
        script_path = str(Path(__file__).resolve().parents[1] / "scripts" / "smoke_check.py")

        # JSON mode
        proc = subprocess.run(
            [sys.executable, script_path, self.base_url, "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertTrue(data["all_passed"])
        self.assertEqual(data["total_checks"], 2)
        self.assertEqual(data["passed_checks"], 2)
        self.assertEqual(data["failed_checks"], 0)

        # Quiet mode
        proc_q = subprocess.run(
            [sys.executable, script_path, self.base_url, "--quiet"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc_q.returncode, 0)
        self.assertNotIn("Target Base URL", proc_q.stdout)
        self.assertIn("PASS Smoke check berhasil", proc_q.stdout)


class MockServerHandler(BaseHTTPRequestHandler):
    """Configurable mock HTTP server for failure scenario testing."""

    responses_config: dict[str, tuple[int, bytes, str, float]] = {}

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        cfg = self.responses_config.get(path)
        if cfg is None:
            try:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.end_headers()
                self.wfile.write(b"Not Found")
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        status, body, content_type, delay = cfg
        if delay > 0:
            time.sleep(delay)

        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


class SmokeCheckFailureScenariosTest(unittest.TestCase):
    """Test failure scenarios: HTTP non-2xx, invalid JSON, timeout, connection refused."""

    def setUp(self) -> None:
        MockServerHandler.responses_config = {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), MockServerHandler)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.script_path = str(Path(__file__).resolve().parents[1] / "scripts" / "smoke_check.py")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_http_non_2xx_failure(self) -> None:
        # Root returns 500, health returns 503
        MockServerHandler.responses_config = {
            "/": (500, b"Internal Server Error", "text/plain", 0.0),
            "/health": (503, json.dumps({"error": "database unavailable"}).encode("utf-8"), "application/json", 0.0),
        }

        all_passed, results = run_smoke_check(self.base_url, timeout=5.0)
        self.assertFalse(all_passed)
        root_res = next(r for r in results if r.name == "root")
        health_res = next(r for r in results if r.name == "health")

        self.assertFalse(root_res.success)
        self.assertEqual(root_res.status_code, 500)
        self.assertIn("500", root_res.message)

        self.assertFalse(health_res.success)
        self.assertEqual(health_res.status_code, 503)
        self.assertIn("503", health_res.message)

        # CLI should return exit code 1
        proc = subprocess.run(
            [sys.executable, self.script_path, self.base_url],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FAIL Smoke check gagal", proc.stderr)
        self.assertIn("[FAIL] ROOT", proc.stdout)
        self.assertIn("[FAIL] HEALTH", proc.stdout)

    def test_invalid_json_health_response(self) -> None:
        # Root 200 OK HTML, health returns HTML error page instead of JSON
        MockServerHandler.responses_config = {
            "/": (200, b"<!DOCTYPE html><html>MarketStudio</html>", "text/html", 0.0),
            "/health": (200, b"<html>502 Bad Gateway</html>", "text/html", 0.0),
        }

        all_passed, results = run_smoke_check(self.base_url, timeout=5.0)
        self.assertFalse(all_passed)
        health_res = next(r for r in results if r.name == "health")
        self.assertFalse(health_res.success)
        self.assertEqual(health_res.status_code, 200)
        self.assertIn("bukan format JSON valid", health_res.message)

        proc = subprocess.run(
            [sys.executable, self.script_path, self.base_url],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("[FAIL] HEALTH", proc.stdout)
        self.assertIn("bukan format JSON valid", proc.stdout)

    def test_invalid_health_status_not_ok(self) -> None:
        # Health returns valid JSON but status is "degraded"
        MockServerHandler.responses_config = {
            "/": (200, b"<!DOCTYPE html><html>MarketStudio</html>", "text/html", 0.0),
            "/health": (200, b'{"status": "degraded", "service": "marketstudio"}', "application/json", 0.0),
        }

        all_passed, results = run_smoke_check(self.base_url, timeout=5.0)
        self.assertFalse(all_passed)
        health_res = next(r for r in results if r.name == "health")
        self.assertFalse(health_res.success)
        self.assertIn("bukan 'ok'", health_res.message)
        self.assertIn("'degraded'", health_res.message)

        proc = subprocess.run(
            [sys.executable, self.script_path, self.base_url],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Status /health bukan 'ok'", proc.stdout)

    def test_invalid_health_json_type_non_object(self) -> None:
        # Health returns valid JSON array instead of object
        MockServerHandler.responses_config = {
            "/": (200, b"<!DOCTYPE html><html>MarketStudio</html>", "text/html", 0.0),
            "/health": (200, b'["ok"]', "application/json", 0.0),
        }

        all_passed, results = run_smoke_check(self.base_url, timeout=5.0)
        self.assertFalse(all_passed)
        health_res = next(r for r in results if r.name == "health")
        self.assertFalse(health_res.success)
        self.assertIn("bukan JSON object", health_res.message)

    def test_invalid_root_content(self) -> None:
        # Root returns 200 OK but content is empty
        MockServerHandler.responses_config = {
            "/": (200, b"", "text/html", 0.0),
            "/health": (200, b'{"status": "ok"}', "application/json", 0.0),
        }
        all_passed, results = run_smoke_check(self.base_url, timeout=5.0)
        self.assertFalse(all_passed)
        root_res = next(r for r in results if r.name == "root")
        self.assertFalse(root_res.success)
        self.assertIn("kosong (0 bytes)", root_res.message)

        # Root returns 200 OK with non-empty text but without HTML or MarketStudio marker
        MockServerHandler.responses_config = {
            "/": (200, b"Random unrelated plain text payload", "text/plain", 0.0),
            "/health": (200, b'{"status": "ok"}', "application/json", 0.0),
        }
        all_passed2, results2 = run_smoke_check(self.base_url, timeout=5.0)
        self.assertFalse(all_passed2)
        root_res2 = next(r for r in results2 if r.name == "root")
        self.assertFalse(root_res2.success)
        self.assertIn("marker HTML atau MarketStudio", root_res2.message)

    def test_network_timeout(self) -> None:
        # Health check delays response for 0.6s with timeout 0.1s
        MockServerHandler.responses_config = {
            "/": (200, b"<!DOCTYPE html><html>MarketStudio</html>", "text/html", 0.0),
            "/health": (200, b'{"status": "ok"}', "application/json", 0.6),
        }

        all_passed, results = run_smoke_check(self.base_url, timeout=0.1)
        self.assertFalse(all_passed)
        health_res = next(r for r in results if r.name == "health")
        self.assertFalse(health_res.success)
        self.assertIn("batas waktu", health_res.message.lower())

        proc = subprocess.run(
            [sys.executable, self.script_path, self.base_url, "--timeout", "0.1"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("[FAIL] HEALTH", proc.stdout)


class SmokeCheckValidationAndNetworkErrorsTest(unittest.TestCase):
    """Test CLI argument validation, normalization, and connection refused error."""

    def setUp(self) -> None:
        self.script_path = str(Path(__file__).resolve().parents[1] / "scripts" / "smoke_check.py")

    def test_url_normalization(self) -> None:
        self.assertEqual(normalize_base_url("http://127.0.0.1:8000/"), "http://127.0.0.1:8000")
        self.assertEqual(normalize_base_url("https://staging.marketstudio.id/app/"), "https://staging.marketstudio.id/app")
        with self.assertRaises(ValueError):
            normalize_base_url("ftp://127.0.0.1:8000")
        with self.assertRaises(ValueError):
            normalize_base_url("not_a_url")

    def test_connection_refused(self) -> None:
        # Bind to a port and close immediately to find an unused port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            unused_port = s.getsockname()[1]

        dead_url = f"http://127.0.0.1:{unused_port}"
        all_passed, results = run_smoke_check(dead_url, timeout=1.0)
        self.assertFalse(all_passed)
        for r in results:
            self.assertFalse(r.success)
            self.assertIn("Koneksi ditolak", r.message)

        proc = subprocess.run(
            [sys.executable, self.script_path, dead_url, "-t", "1.0"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Koneksi ditolak", proc.stdout)

    def test_cli_argument_errors_return_exit_code_2(self) -> None:
        # 1. Missing URL
        proc_no_url = subprocess.run(
            [sys.executable, self.script_path],
            capture_output=True,
            text=True,
            env={},  # clear env so MARKETSTUDIO_BASE_URL is not set
            check=False,
        )
        self.assertEqual(proc_no_url.returncode, 2)
        self.assertIn("Target base URL tidak ditentukan", proc_no_url.stderr)

        # 2. Invalid URL scheme
        proc_bad_url = subprocess.run(
            [sys.executable, self.script_path, "ftp://localhost:8000"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc_bad_url.returncode, 2)
        self.assertIn("Skema harus http:// atau https://", proc_bad_url.stderr)

        # 3. Invalid timeout <= 0
        proc_bad_to = subprocess.run(
            [sys.executable, self.script_path, "http://127.0.0.1:8000", "--timeout", "0"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc_bad_to.returncode, 2)
        self.assertIn("Nilai timeout harus positif", proc_bad_to.stderr)

        # 4. Invalid env timeout format
        env = {"MARKETSTUDIO_BASE_URL": "http://127.0.0.1:8000", "MARKETSTUDIO_SMOKE_TIMEOUT": "invalid_number"}
        proc_bad_env_to = subprocess.run(
            [sys.executable, self.script_path],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(proc_bad_env_to.returncode, 2)
        self.assertIn("Format timeout dari environment variable tidak valid", proc_bad_env_to.stderr)


if __name__ == "__main__":
    unittest.main()
