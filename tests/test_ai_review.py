"""Integration & unit tests for AI Business Review (#14/#40/#41)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from app.db import db_transaction, init_db
from app.server import create_server
from app.service import BaselineService

_ALL_TABLES = (
    "workspaces",
    "workspace_memberships",
    "sessions",
    "offerings",
    "inventory_batches",
    "inventory_pools",
    "stock_movements",
    "purchases",
    "sales",
    "sale_lines",
    "cash_movements",
    "idempotency_records",
    "audit_events",
)


class AIReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "ai_review_test.sqlite3")
        init_db(self.db_path)
        self.service = BaselineService(db_path=self.db_path)
        self.server = create_server(host="127.0.0.1", port=0, db_path=self.db_path)
        self.port = self.server.server_port
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

        self.owner_actor = "owner_ai_1"
        _, self.ws = self.service.create_workspace(
            {"name": "Warung Rahasia AI", "timezone": "Asia/Jakarta"},
            actor=self.owner_actor,
        )
        self.ws_id = self.ws["workspace_id"]
        _, self.off_prod = self.service.create_offering(
            self.ws_id,
            actor_id=self.owner_actor,
            payload={"name": "Kopi Susu", "offering_type": "goods", "unit_price_idr": 15000, "unit": "cup"},
        )
        _, self.off_svc = self.service.create_offering(
            self.ws_id,
            actor_id=self.owner_actor,
            payload={"name": "Antar Kurir", "offering_type": "service", "unit_price_idr": 10000, "unit": "order"},
        )
        self.service.create_purchase(
            self.ws_id,
            actor_id=self.owner_actor,
            payload={"offering_id": self.off_prod["offering_id"], "qty": "10", "total_cost_idr": 80000},
        )
        self.service.create_sale(
            self.ws_id,
            actor_id=self.owner_actor,
            payload={
                "lines": [
                    {"offering_id": self.off_prod["offering_id"], "qty": "2"},
                    {"offering_id": self.off_svc["offering_id"], "qty": "1"},
                ]
            },
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
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

    def test_provider_config_check_never_exposes_secrets(self) -> None:
        secret_val = "AIzaSy_SECRET_DO_NOT_LEAK_999"
        with mock.patch.dict(
            os.environ,
            {
                "MARKETSTUDIO_AI_PROVIDER": "gemini",
                "MARKETSTUDIO_AI_MODEL": "gemini-2.5-flash",
                "GEMINI_API_KEY": secret_val,
            },
            clear=False,
        ):
            cfg = self.service.get_ai_review_config(self.ws_id, self.owner_actor)
            self.assertTrue(cfg["configured"])
            self.assertEqual(cfg["provider"], "gemini")
            self.assertEqual(cfg["model"], "gemini-2.5-flash")
            self.assertTrue(cfg["env_presence"]["GEMINI_API_KEY"])
            self.assertEqual(cfg["missing_env_vars"], [])
            self.assertNotIn(secret_val, json.dumps(cfg))

    def test_outbound_payload_minimization_and_valid_live_like_response(self) -> None:
        captured_payloads: list[dict] = []

        def fake_live_provider(outbound_payload: dict) -> dict:
            captured_payloads.append(outbound_payload)
            return {
                "summary": "Omzet terjaga baik dengan satu layanan berstatus HPP open.",
                "highlights": ["Penjualan produk dan layanan tercatat."],
                "missing_data": ["cogs_open", "tax_status: not_assessed"],
                "citations": {
                    "snapshot_id": outbound_payload["snapshot_id"],
                    "period_date": outbound_payload["period"]["date"],
                    "source_ids": outbound_payload["source_ids"],
                },
            }

        before = self._table_counts()
        res = self.service.run_daily_ai_review(
            self.ws_id,
            self.owner_actor,
            payload={},
            provider_callable=fake_live_provider,
        )
        after = self._table_counts()
        self.assertEqual(before, after)
        self.assertEqual(res["status"], "succeeded")
        self.assertEqual(res["provider_mode"], "live_provider")
        self.assertIsNone(res["fallback_reason"])

        self.assertEqual(len(captured_payloads), 1)
        sent_json = json.dumps(captured_payloads[0])
        self.assertNotIn("Warung Rahasia AI", sent_json)
        self.assertNotIn(self.ws_id, sent_json)
        self.assertNotIn(self.owner_actor, sent_json)
        self.assertIn("IDR", sent_json)

    def test_deterministic_fallback_on_all_failure_modes(self) -> None:
        before = self._table_counts()

        # 1. Unconfigured
        with mock.patch.dict(os.environ, {}, clear=True):
            r_unconf = self.service.run_daily_ai_review(self.ws_id, self.owner_actor, payload={})
            self.assertEqual(r_unconf["status"], "fallback")
            self.assertEqual(r_unconf["provider_mode"], "deterministic_fallback")
            self.assertEqual(r_unconf["fallback_reason"], "provider_unconfigured")
            self.assertIn("Ringkasan deterministik", r_unconf["review"]["summary"])
            self.assertTrue(any("cogs_open" in m for m in r_unconf["review"]["missing_data"]))

        # 2. Stub failure modes
        expected_reasons = {
            "stub_timeout": "provider_timeout",
            "stub_error": "provider_error",
            "stub_empty": "empty_response",
            "stub_fake_citation": "fake_citation",
            "stub_wrong_period": "period_mismatch",
        }
        for stub_mode, expected_reason in expected_reasons.items():
            res = self.service.run_daily_ai_review(
                self.ws_id,
                self.owner_actor,
                payload={"stub_mode": stub_mode},
            )
            self.assertEqual(res["status"], "fallback", msg=stub_mode)
            self.assertEqual(res["provider_mode"], "deterministic_fallback", msg=stub_mode)
            self.assertEqual(res["fallback_reason"], expected_reason, msg=stub_mode)
            self.assertIn("Ringkasan deterministik", res["review"]["summary"])

        # 3. Valid stub
        r_stub_ok = self.service.run_daily_ai_review(
            self.ws_id,
            self.owner_actor,
            payload={"stub_mode": "stub_valid"},
        )
        self.assertEqual(r_stub_ok["status"], "succeeded")
        self.assertEqual(r_stub_ok["provider_mode"], "stub_test")
        self.assertTrue(r_stub_ok["is_stub"])

        after = self._table_counts()
        self.assertEqual(before, after)

    def test_tenant_isolation_401_and_404_http(self) -> None:
        import urllib.error
        import urllib.request

        base = f"http://127.0.0.1:{self.port}"
        # 401 unauthenticated
        req_unauth = urllib.request.Request(
            f"{base}/v1/workspaces/{self.ws_id}/reports/daily/ai-review",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx_401:
            urllib.request.urlopen(req_unauth)
        self.assertEqual(ctx_401.exception.code, 401)
        ctx_401.exception.close()

        # 404 non-member & unknown workspace via service (anti-enumeration)
        from app.domain import DomainError

        with self.assertRaises(DomainError) as ctx_404:
            self.service.run_daily_ai_review(self.ws_id, "intruder_99", payload={})
        self.assertEqual(ctx_404.exception.status_code, 404)

        with self.assertRaises(DomainError) as ctx_unknown:
            self.service.run_daily_ai_review("ws_unknown_999", self.owner_actor, payload={})
        self.assertEqual(ctx_unknown.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
