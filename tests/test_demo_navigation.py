"""Tests for Issue #55: Responsive navigation, isolated demo fixture oracle, and migration."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path

os.environ["MARKETSTUDIO_QUIET_LOGS"] = "1"

from app.db import db_transaction, init_db  # noqa: E402
from app.server import create_server  # noqa: E402
from app.service import DEMO_SCENARIO_SLUG, BaselineService  # noqa: E402


class DemoNavigationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "test_demo_nav.sqlite3")
        self.server = create_server(host="127.0.0.1", port=0, db_path=self.db_path)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.token_a = self._login("actor_a", "dev-a-pass")
        self.token_b = self._login("actor_b", "dev-b-pass")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmpdir.cleanup()

    def _login(self, actor_id: str, passcode: str) -> str:
        status, res = self._request("POST", "/v1/sessions", {"actor_id": actor_id, "passcode": passcode})
        self.assertEqual(status, 201)
        return res["item"]["token"]

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        headers: dict[str, str] | None = None,
        token: str | None = None,
    ) -> tuple[int, dict]:
        req_headers = dict(headers or {})
        if token:
            req_headers["Authorization"] = f"Bearer {token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=req_headers, method=method
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body_bytes = exc.read()
            exc.close()
            return exc.code, json.loads(body_bytes.decode("utf-8"))

    def test_demo_bootstrap_idempotent_and_oracle(self) -> None:
        s1, d1 = self._request(
            "POST",
            "/v1/workspaces/demo",
            {"scenario_slug": DEMO_SCENARIO_SLUG},
            token=self.token_a,
        )
        self.assertEqual(s1, 201)
        item1 = d1["item"]
        self.assertTrue(item1["created"])
        self.assertFalse(item1["idempotent_replay"])
        ws_id = item1["workspace"]["workspace_id"]
        self.assertTrue(item1["workspace"]["is_demo"])
        self.assertEqual(item1["workspace"]["demo_slug"], DEMO_SCENARIO_SLUG)

        # Second click must be idempotent without duplicating records
        s2, d2 = self._request(
            "POST",
            "/v1/workspaces/demo",
            {"scenario_slug": DEMO_SCENARIO_SLUG},
            token=self.token_a,
        )
        self.assertEqual(s2, 200)
        self.assertFalse(d2["item"]["created"])
        self.assertTrue(d2["item"]["idempotent_replay"])
        self.assertEqual(d2["item"]["workspace"]["workspace_id"], ws_id)

        with db_transaction(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM offerings WHERE workspace_id = ?", (ws_id,)).fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM purchases WHERE workspace_id = ?", (ws_id,)).fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sales WHERE workspace_id = ?", (ws_id,)).fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM stock_movements WHERE workspace_id = ?", (ws_id,)).fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cash_movements WHERE workspace_id = ?", (ws_id,)).fetchone()[0], 3)

        # Verify offerings include actual stock qty & WA value
        s_off, d_off = self._request("GET", f"/v1/workspaces/{ws_id}/offerings", token=self.token_a)
        self.assertEqual(s_off, 200)
        by_name = {o["name"]: o for o in d_off["items"]}
        self.assertEqual(by_name["Bakso Urat"]["qty_on_hand"], "6")
        self.assertEqual(by_name["Bakso Urat"]["inventory_value_idr"], 54000)
        self.assertEqual(by_name["Bakso Urat"]["wa_unit_cost_idr"], 9000)
        self.assertEqual(by_name["Beras Medium"]["qty_on_hand"], "10")
        self.assertEqual(by_name["Beras Medium"]["inventory_value_idr"], 120000)
        self.assertEqual(by_name["Beras Medium"]["wa_unit_cost_idr"], 12000)
        self.assertIsNone(by_name["Jasa Katering Acara"]["qty_on_hand"])
        self.assertIsNone(by_name["Jasa Katering Acara"]["inventory_value_idr"])

        # Verify exact combined Oracle on daily report
        demo_date = item1["demo_date"]
        s_rep, d_rep = self._request(
            "GET",
            f"/v1/workspaces/{ws_id}/reports/daily?date={demo_date}",
            token=self.token_a,
        )
        self.assertEqual(s_rep, 200)
        rep = d_rep["report"]
        self.assertEqual(rep["revenue_idr"], 60000)
        self.assertEqual(rep["cogs_idr"], 36000)
        self.assertEqual(rep["gross_profit_idr"], 24000)
        self.assertEqual(rep["cash_in_idr"], 60000)
        self.assertEqual(rep["cash_out_idr"], 210000)
        self.assertEqual(rep["net_cash_flow_idr"], -150000)
        self.assertEqual(rep["ending_inventory"]["total_value_idr"], 174000)
        self.assertEqual(rep["tax_status"], "not_assessed")

        inv_map = {it["name"]: it for it in rep["ending_inventory"]["items"]}
        self.assertEqual(inv_map["Bakso Urat"]["qty_remaining"], "6")
        self.assertEqual(inv_map["Bakso Urat"]["value_idr"], 54000)
        self.assertEqual(inv_map["Beras Medium"]["qty_remaining"], "10")
        self.assertEqual(inv_map["Beras Medium"]["value_idr"], 120000)

        # Verify human-readable drill-down fields
        self.assertEqual(rep["drill_down"]["purchases"][0]["offering_name"], "Bakso Urat")
        self.assertEqual(rep["drill_down"]["sales"][0]["lines"][0]["offering_name"], "Bakso Urat")
        self.assertEqual(rep["drill_down"]["stock_movements"][0]["offering_name"], "Bakso Urat")

    def test_manual_tutup_hari_followup_after_demo(self) -> None:
        _, d_demo = self._request("POST", "/v1/workspaces/demo", {}, token=self.token_a)
        ws_id = d_demo["item"]["workspace"]["workspace_id"]
        demo_date = d_demo["item"]["demo_date"]

        _, d_off = self._request("GET", f"/v1/workspaces/{ws_id}/offerings", token=self.token_a)
        bakso = next(o for o in d_off["items"] if o["name"] == "Bakso Urat")

        s_sale, d_sale = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": bakso["offering_id"], "qty": "2", "total_price_idr": 30000}]},
            headers={"Idempotency-Key": "tutup-hari-1"},
            token=self.token_a,
        )
        self.assertEqual(s_sale, 201)
        self.assertEqual(d_sale["item"]["total_cogs_idr"], 18000)
        self.assertEqual(d_sale["item"]["gross_profit_idr"], 12000)

        # Re-clicking demo load stays idempotent and keeps manual follow-up intact
        s_re, _ = self._request("POST", "/v1/workspaces/demo", {}, token=self.token_a)
        self.assertEqual(s_re, 200)

        _, d_off_after = self._request("GET", f"/v1/workspaces/{ws_id}/offerings", token=self.token_a)
        bakso_after = next(o for o in d_off_after["items"] if o["name"] == "Bakso Urat")
        self.assertEqual(bakso_after["qty_on_hand"], "4")
        self.assertEqual(bakso_after["inventory_value_idr"], 36000)

        _, d_rep = self._request("GET", f"/v1/workspaces/{ws_id}/reports/daily?date={demo_date}", token=self.token_a)
        rep = d_rep["report"]
        self.assertEqual(rep["revenue_idr"], 90000)
        self.assertEqual(rep["cogs_idr"], 54000)
        self.assertEqual(rep["gross_profit_idr"], 36000)
        self.assertEqual(rep["net_cash_flow_idr"], -120000)
        self.assertEqual(rep["ending_inventory"]["total_value_idr"], 156000)

    def test_demo_tenant_isolation_and_owner_workspace_preservation(self) -> None:
        # 401 unauthenticated
        s401, _ = self._request("POST", "/v1/workspaces/demo", {})
        self.assertEqual(s401, 401)

        # Invalid scenario slug -> 422
        s422, d422 = self._request("POST", "/v1/workspaces/demo", {"scenario_slug": "unknown"}, token=self.token_a)
        self.assertEqual(s422, 422)
        self.assertEqual(d422["code"], "invalid_demo_scenario")

        # Real workspace owned by actor_a remains untouched
        _, real_ws_res = self._request("POST", "/v1/workspaces", {"name": "Usaha Nyata Pemilik"}, token=self.token_a)
        real_ws_id = real_ws_res["item"]["workspace_id"]
        self.assertFalse(real_ws_res["item"]["is_demo"])

        _, demo_a = self._request("POST", "/v1/workspaces/demo", {}, token=self.token_a)
        ws_a_demo = demo_a["item"]["workspace"]["workspace_id"]
        self.assertNotEqual(real_ws_id, ws_a_demo)

        _, real_offerings = self._request("GET", f"/v1/workspaces/{real_ws_id}/offerings", token=self.token_a)
        self.assertEqual(real_offerings["items"], [])

        # actor_b gets separate demo workspace and cannot access actor_a's demo workspace
        _, demo_b = self._request("POST", "/v1/workspaces/demo", {}, token=self.token_b)
        ws_b_demo = demo_b["item"]["workspace"]["workspace_id"]
        self.assertNotEqual(ws_a_demo, ws_b_demo)

        s404, _ = self._request("GET", f"/v1/workspaces/{ws_a_demo}/offerings", token=self.token_b)
        self.assertEqual(s404, 404)

    def test_legacy_db_migration_preserves_existing_owner_data(self) -> None:
        legacy_db = str(Path(self.tmpdir.name) / "legacy.sqlite3")
        with closing(sqlite3.connect(legacy_db)) as conn:
            conn.executescript(
                """
                CREATE TABLE workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    business_type TEXT NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'IDR',
                    timezone TEXT NOT NULL DEFAULT 'Asia/Jakarta',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE workspace_memberships (
                    workspace_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'owner',
                    created_at TEXT NOT NULL,
                    revoked_at TEXT,
                    PRIMARY KEY (workspace_id, actor_id)
                );
                INSERT INTO workspaces (workspace_id, name, business_type, currency, timezone, created_at)
                VALUES ('ws_legacy_1', 'Toko Lama', 'goods_retail', 'IDR', 'Asia/Jakarta', '2026-11-26T10:00:00+00:00');
                INSERT INTO workspace_memberships (workspace_id, actor_id, role, created_at, revoked_at)
                VALUES ('ws_legacy_1', 'actor_a', 'owner', '2026-11-26T10:00:00+00:00', NULL);
                """
            )
            conn.commit()

        init_db(legacy_db)
        svc = BaselineService(db_path=legacy_db)
        wss = svc.list_workspaces("actor_a")
        self.assertEqual(len(wss), 1)
        self.assertEqual(wss[0]["workspace_id"], "ws_legacy_1")
        self.assertEqual(wss[0]["name"], "Toko Lama")
        self.assertFalse(wss[0]["is_demo"])
        self.assertIsNone(wss[0]["demo_slug"])

    def test_html_ui_navigation_a11y_oracle_and_xss_safety(self) -> None:
        with urllib.request.urlopen(f"{self.base_url}/") as resp:
            self.assertEqual(resp.status, 200)
            html = resp.read().decode("utf-8")

        self.assertIn("MarketStudio", html)
        self.assertNotIn(".innerHTML", html)
        self.assertIn("catalogReqSeq", html)
        self.assertIn("reportReqSeq", html)
        self.assertIn("getScopedKey", html)

        # Accessibility & navigation anchors
        self.assertIn("Langsung ke konten utama", html)
        self.assertIn('aria-current', html)
        self.assertIn(':focus-visible', html)
        self.assertIn('aria-live="polite"', html)

        # Deep links & 6 Studio architecture with honest Preview / Roadmap status
        for anchor in ("#ringkasan", "#transaksi", "#katalog", "#analisis", "#profil", "#studio-intelligence"):
            self.assertIn(anchor, html)
        for studio in (
            "Business Studio",
            "Intelligence Studio",
            "Spreadsheet Studio",
            "Creative Studio",
            "Commerce Studio",
            "Social Studio",
        ):
            self.assertIn(studio, html)
        self.assertIn("Roadmap", html)
        self.assertNotIn("Cari apa saja", html)

        # AI Business Review (#14/#40/#41) UI elements & stale-result clearing preserved
        for ai_id in (
            "aiReviewCard",
            "aiStubMode",
            "runAiReviewBtn",
            "clearAiReviewResults",
            "aiReviewReqSeq",
            "resetWorkspaceScopedUiState",
            "overscroll-behavior: contain",
        ):
            self.assertIn(ai_id, html)

        # Exact Oracle verification in user scenario cards
        self.assertIn("-Rp 150.000", html)
        self.assertIn("Rp 174.000", html)

    def test_demo_replay_demo_date_stays_deterministic_across_midnight(self) -> None:
        s1, d1 = self._request("POST", "/v1/workspaces/demo", {}, token=self.token_a)
        self.assertEqual(s1, 201)
        ws_id = d1["item"]["workspace"]["workspace_id"]

        # Simulate seed created on 2026-11-25 Asia/Jakarta (03:00 UTC = 10:00 WIB)
        past_utc = "2026-11-25T03:00:00+00:00"
        with db_transaction(self.db_path, immediate=True) as conn:
            conn.execute("UPDATE workspaces SET created_at = ? WHERE workspace_id = ?", (past_utc, ws_id))
            conn.execute("UPDATE purchases SET occurred_at = ? WHERE workspace_id = ?", (past_utc, ws_id))
            conn.execute("UPDATE sales SET occurred_at = ? WHERE workspace_id = ?", (past_utc, ws_id))
            conn.execute("UPDATE stock_movements SET occurred_at = ? WHERE workspace_id = ?", (past_utc, ws_id))
            conn.execute("UPDATE cash_movements SET occurred_at = ? WHERE workspace_id = ?", (past_utc, ws_id))

        s2, d2 = self._request("POST", "/v1/workspaces/demo", {}, token=self.token_a)
        self.assertEqual(s2, 200)
        self.assertTrue(d2["item"]["idempotent_replay"])
        self.assertEqual(d2["item"]["demo_date"], "2026-11-25")

        s_rep, d_rep = self._request(
            "GET",
            f"/v1/workspaces/{ws_id}/reports/daily?date=2026-11-25",
            token=self.token_a,
        )
        self.assertEqual(s_rep, 200)
        self.assertEqual(d_rep["report"]["net_cash_flow_idr"], -150000)
        self.assertEqual(d_rep["report"]["ending_inventory"]["total_value_idr"], 174000)


if __name__ == "__main__":
    unittest.main()
