"""Contract tests for 9Router OpenAI-compatible AI Business Review adapter (Issue #14)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from app.ai_review import (
    DEFAULT_9ROUTER_MODEL,
    DEFAULT_9ROUTER_URL,
    call_9router_json,
    execute_ai_review,
    get_ai_provider_config_status,
)
from app.db import db_transaction, init_db
from app.service import BaselineService


class _Mock9RouterHandler(BaseHTTPRequestHandler):
    mode = "valid"
    received_requests: list[dict] = []

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8")
        parsed_body = json.loads(body) if body else {}
        _Mock9RouterHandler.received_requests.append({
            "path": self.path,
            "headers": dict(self.headers),
            "body": parsed_body,
        })

        if _Mock9RouterHandler.mode == "timeout":
            time.sleep(0.5)
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")
            except OSError:
                pass
            return

        if _Mock9RouterHandler.mode == "http_500":
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": {"message": "Internal gateway error"}}')
            return

        user_content = ""
        for m in parsed_body.get("messages", []):
            if m.get("role") == "user":
                user_content = m.get("content", "")

        outbound = {}
        try:
            if "\n{" in user_content:
                json_part = user_content[user_content.index("\n{") + 1 :]
                outbound = json.loads(json_part)
        except Exception:
            outbound = {}

        snapshot_id = outbound.get("snapshot_id", "snap_test")
        period_date = outbound.get("period", {}).get("date", "2026-11-28")
        source_ids = outbound.get("source_ids", [])
        metrics = outbound.get("metrics", {})

        if _Mock9RouterHandler.mode == "fake_citation":
            content_obj = {
                "summary": "Ringkasan dengan rujukan palsu.",
                "highlights": ["Temuan tidak valid."],
                "missing_data": [],
                "citations": {
                    "snapshot_id": snapshot_id,
                    "period_date": period_date,
                    "source_ids": ["sale_nonexistent_999"],
                },
            }
        elif _Mock9RouterHandler.mode == "numeric_mismatch":
            content_obj = {
                "summary": "Ringkasan dengan angka dipalsukan.",
                "highlights": ["Klaim omzet lebih tinggi."],
                "missing_data": [],
                "numeric_claims": {
                    "revenue_idr": (metrics.get("revenue_idr") or 0) + 1000000,
                },
                "citations": {
                    "snapshot_id": snapshot_id,
                    "period_date": period_date,
                    "source_ids": source_ids,
                },
            }
        elif _Mock9RouterHandler.mode == "markdown_fenced":
            inner = json.dumps({
                "summary": f"[9Router ag/gemini-3.8-flash] Omzet Rp{metrics.get('revenue_idr', 0):,}.",
                "highlights": [f"Terverifikasi {len(source_ids)} data transaksi."],
                "missing_data": ["tax_status: not_assessed"],
                "citations": {
                    "snapshot_id": snapshot_id,
                    "period_date": period_date,
                    "source_ids": source_ids,
                },
            })
            content_text = f"```json\n{inner}\n```"
            response_payload = {
                "id": "chatcmpl-mock-9router-1",
                "object": "chat.completion",
                "created": 1764374400,
                "model": "ag/gemini-3.8-flash",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": content_text},
                    "finish_reason": "stop",
                }],
            }
            encoded = json.dumps(response_payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return
        else:  # valid
            content_obj = {
                "summary": f"[9Router ag/gemini-3.8-flash] Periode {period_date}: Omzet Rp{metrics.get('revenue_idr', 0):,}.",
                "highlights": [
                    f"Transaksi tercatat: {metrics.get('sales_count', 0)} penjualan.",
                    f"Arus kas bersih: Rp{metrics.get('net_cash_flow_idr', 0):,}.",
                ],
                "missing_data": ["tax_status: not_assessed"],
                "numeric_claims": {
                    "revenue_idr": metrics.get("revenue_idr", 0),
                    "net_cash_flow_idr": metrics.get("net_cash_flow_idr", 0),
                },
                "citations": {
                    "snapshot_id": snapshot_id,
                    "period_date": period_date,
                    "source_ids": source_ids,
                },
            }

        response_payload = {
            "id": "chatcmpl-mock-9router-1",
            "object": "chat.completion",
            "created": 1764374400,
            "model": "ag/gemini-3.8-flash",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps(content_obj)},
                "finish_reason": "stop",
            }],
        }
        encoded = json.dumps(response_payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class NineRouterContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _Mock9RouterHandler.received_requests = []
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Mock9RouterHandler)
        cls.port = cls.server.server_port
        cls.server_url = f"http://127.0.0.1:{cls.port}/v1/chat/completions"
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        _Mock9RouterHandler.mode = "valid"
        _Mock9RouterHandler.received_requests.clear()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "9router_test.sqlite3")
        init_db(self.db_path)
        self.service = BaselineService(db_path=self.db_path)

        self.owner = "owner_9router"
        _, self.ws = self.service.create_workspace(
            {"name": "Warung Kopi 9Router", "timezone": "Asia/Jakarta"},
            actor=self.owner,
        )
        self.ws_id = self.ws["workspace_id"]
        _, self.off = self.service.create_offering(
            self.ws_id,
            actor_id=self.owner,
            payload={"name": "Kopi Tubruk", "offering_type": "goods", "unit_price_idr": 10000, "unit": "cup"},
        )
        self.service.create_purchase(
            self.ws_id,
            actor_id=self.owner,
            payload={"offering_id": self.off["offering_id"], "qty": "20", "total_cost_idr": 100000},
        )
        self.service.create_sale(
            self.ws_id,
            actor_id=self.owner,
            payload={"lines": [{"offering_id": self.off["offering_id"], "qty": "5"}]},
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _table_counts(self) -> dict[str, int]:
        with db_transaction(self.db_path) as conn:
            tables = [
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            ]
            return {
                t: conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"]
                for t in tables
            }

    def test_opt_in_config_status_and_secret_redaction(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "MARKETSTUDIO_AI_PROVIDER": "9router",
                "MARKETSTUDIO_9ROUTER_URL": self.server_url,
                "MARKETSTUDIO_9ROUTER_MODEL": "ag/gemini-3.8-flash",
                "MARKETSTUDIO_9ROUTER_API_KEY": "secret-key-do-not-leak",
            },
            clear=False,
        ):
            status = get_ai_provider_config_status()
            self.assertTrue(status["configured"])
            self.assertEqual(status["provider"], "9router")
            self.assertEqual(status["model"], "ag/gemini-3.8-flash")
            self.assertFalse(status["unsupported_provider"])
            self.assertIn("9Router lokal", status["setup_action"])
            # Secret must never appear in serialized status
            dumped = json.dumps(status)
            self.assertNotIn("secret-key-do-not-leak", dumped)

    def test_9router_valid_roundtrip_contract(self) -> None:
        before = self._table_counts()
        with mock.patch.dict(
            os.environ,
            {
                "MARKETSTUDIO_AI_PROVIDER": "9router",
                "MARKETSTUDIO_9ROUTER_URL": self.server_url,
                "MARKETSTUDIO_9ROUTER_MODEL": "ag/gemini-3.8-flash",
                "MARKETSTUDIO_9ROUTER_API_KEY": "test-key-123",
            },
            clear=False,
        ):
            res = self.service.run_daily_ai_review(self.ws_id, self.owner, payload={})
            self.assertEqual(res["status"], "succeeded")
            self.assertEqual(res["provider_mode"], "live_provider")
            self.assertIsNone(res["fallback_reason"])
            self.assertEqual(res["config_status"]["provider"], "9router")
            self.assertIn("ag/gemini-3.8-flash", res["review"]["summary"])

            # Verify outbound request structure received by mock 9router
            self.assertEqual(len(_Mock9RouterHandler.received_requests), 1)
            req = _Mock9RouterHandler.received_requests[0]
            self.assertEqual(req["path"], "/v1/chat/completions")
            self.assertEqual(req["headers"].get("Authorization"), "Bearer test-key-123")
            self.assertEqual(req["body"]["model"], "ag/gemini-3.8-flash")

            # Outbound payload minimization: no workspace_id, actor_id, or business name sent to 9router
            sent_str = json.dumps(req["body"])
            self.assertNotIn(self.ws_id, sent_str)
            self.assertNotIn(self.owner, sent_str)
            self.assertNotIn("Warung Kopi 9Router", sent_str)

        after = self._table_counts()
        self.assertEqual(before, after)

    def test_9router_markdown_fenced_response_handling(self) -> None:
        _Mock9RouterHandler.mode = "markdown_fenced"
        with mock.patch.dict(
            os.environ,
            {
                "MARKETSTUDIO_AI_PROVIDER": "9router",
                "MARKETSTUDIO_9ROUTER_URL": self.server_url,
            },
            clear=False,
        ):
            res = self.service.run_daily_ai_review(self.ws_id, self.owner, payload={})
            self.assertEqual(res["status"], "succeeded")
            self.assertEqual(res["provider_mode"], "live_provider")
            self.assertIn("Omzet", res["review"]["summary"])

    def test_9router_fake_citation_rejected_to_deterministic_fallback(self) -> None:
        _Mock9RouterHandler.mode = "fake_citation"
        with mock.patch.dict(
            os.environ,
            {
                "MARKETSTUDIO_AI_PROVIDER": "9router",
                "MARKETSTUDIO_9ROUTER_URL": self.server_url,
            },
            clear=False,
        ):
            res = self.service.run_daily_ai_review(self.ws_id, self.owner, payload={})
            self.assertEqual(res["status"], "fallback")
            self.assertEqual(res["provider_mode"], "deterministic_fallback")
            self.assertEqual(res["fallback_reason"], "fake_citation")
            self.assertIn("Ringkasan deterministik", res["review"]["summary"])

    def test_9router_numeric_mismatch_rejected_to_deterministic_fallback(self) -> None:
        _Mock9RouterHandler.mode = "numeric_mismatch"
        with mock.patch.dict(
            os.environ,
            {
                "MARKETSTUDIO_AI_PROVIDER": "9router",
                "MARKETSTUDIO_9ROUTER_URL": self.server_url,
            },
            clear=False,
        ):
            res = self.service.run_daily_ai_review(self.ws_id, self.owner, payload={})
            self.assertEqual(res["status"], "fallback")
            self.assertEqual(res["provider_mode"], "deterministic_fallback")
            self.assertEqual(res["fallback_reason"], "numeric_mismatch")
            self.assertIn("Ringkasan deterministik", res["review"]["summary"])

    def test_9router_timeout_falls_back_deterministically(self) -> None:
        _Mock9RouterHandler.mode = "timeout"
        with mock.patch.dict(
            os.environ,
            {
                "MARKETSTUDIO_AI_PROVIDER": "9router",
                "MARKETSTUDIO_9ROUTER_URL": self.server_url,
            },
            clear=False,
        ):
            res = self.service.run_daily_ai_review(
                self.ws_id, self.owner, payload={"timeout_seconds": 0.1}
            )
            self.assertEqual(res["status"], "fallback")
            self.assertEqual(res["provider_mode"], "deterministic_fallback")
            self.assertEqual(res["fallback_reason"], "provider_timeout")
            self.assertIn("Ringkasan deterministik", res["review"]["summary"])

    def test_9router_http_500_falls_back_deterministically(self) -> None:
        _Mock9RouterHandler.mode = "http_500"
        with mock.patch.dict(
            os.environ,
            {
                "MARKETSTUDIO_AI_PROVIDER": "9router",
                "MARKETSTUDIO_9ROUTER_URL": self.server_url,
            },
            clear=False,
        ):
            res = self.service.run_daily_ai_review(self.ws_id, self.owner, payload={})
            self.assertEqual(res["status"], "fallback")
            self.assertEqual(res["provider_mode"], "deterministic_fallback")
            self.assertEqual(res["fallback_reason"], "provider_error")
            self.assertIn("Ringkasan deterministik", res["review"]["summary"])

    def test_9router_ssrf_rejection_for_non_loopback_urls(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "MARKETSTUDIO_AI_PROVIDER": "9router",
                "MARKETSTUDIO_9ROUTER_URL": "http://192.168.1.100/v1/chat/completions",
            },
            clear=False,
        ):
            res = self.service.run_daily_ai_review(self.ws_id, self.owner, payload={})
            self.assertEqual(res["status"], "fallback")
            self.assertEqual(res["fallback_reason"], "provider_error")


if __name__ == "__main__":
    unittest.main()
