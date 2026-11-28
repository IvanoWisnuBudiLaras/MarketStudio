"""Unit and integration tests for Issue #9: Catalog offerings, unit costing, pricing decisions, and archiving."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app.db import db_transaction
from app.server import create_server


class OfferingPricingTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.db_path = str(Path(directory) / "test_pricing.sqlite3")
        server = create_server(port=0, db_path=self.db_path)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_port}"

        self.token_a = self.login("actor_a", "dev-a-pass")
        self.token_b = self.login("actor_b", "dev-b-pass")
        self.ws_a = self.create_workspace(self.token_a, "Usaha Toko A")
        self.ws_b = self.create_workspace(self.token_b, "Usaha Toko B")

    def request(self, method, path, status, token=None, payload=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as error:
            resp = error
        with resp:
            raw = resp.read()
            self.assertEqual(resp.status, status, raw[:400])
            return json.loads(raw) if raw else {}

    def login(self, actor, passcode):
        res = self.request("POST", "/v1/sessions", 201, payload={"actor_id": actor, "passcode": passcode})
        return res["item"]["token"]

    def create_workspace(self, token, name):
        res = self.request("POST", "/v1/workspaces", 201, token, payload={"name": name})
        return res["item"]["workspace_id"]

    def test_offering_types_and_costing_status(self):
        # 1. Goods without purchase: unit cost is unknown
        res_g = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/offerings",
            201,
            self.token_a,
            {"name": "Bakso Mentah", "offering_type": "goods", "unit_price_idr": 15000, "unit": "pcs"},
        )
        goods = res_g["item"]
        self.assertEqual(goods["cost_status"], "unknown")
        self.assertIsNone(goods["unit_cost_idr"])
        self.assertIsNone(goods["margin_idr"])
        self.assertIsNone(goods["margin_pct"])
        self.assertEqual(goods["cost_source"], "unknown")
        self.assertEqual(goods["status"], "active")
        self.assertFalse(goods["is_archived"])

        # 2. Goods cannot have service_cost_idr
        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/offerings",
            422,
            self.token_a,
            {"name": "Bakso Salah", "offering_type": "goods", "unit_price_idr": 15000, "service_cost_idr": 5000},
        )

        # 3. Service without service_cost_idr: unknown
        res_s1 = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/offerings",
            201,
            self.token_a,
            {"name": "Konsultasi Bisnis", "offering_type": "service", "unit_price_idr": 200000, "unit": "sesi"},
        )
        svc1 = res_s1["item"]
        self.assertEqual(svc1["cost_status"], "unknown")
        self.assertIsNone(svc1["unit_cost_idr"])
        self.assertIsNone(svc1["margin_idr"])
        self.assertFalse(svc1["requires_stock_movement"])

        # 4. Service with service_cost_idr: known cost and margin comparison
        res_s2 = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/offerings",
            201,
            self.token_a,
            {
                "name": "Jasa Reparasi",
                "offering_type": "service",
                "unit_price_idr": 100000,
                "unit": "unit",
                "service_cost_idr": 40000,
            },
        )
        svc2 = res_s2["item"]
        self.assertEqual(svc2["cost_status"], "known")
        self.assertEqual(svc2["unit_cost_idr"], 40000)
        self.assertEqual(svc2["cost_source"], "service_input")
        self.assertEqual(svc2["margin_idr"], 60000)
        self.assertEqual(svc2["margin_pct"], 60.0)

        # 5. Hybrid offering: movement only on stock line, combination costing
        res_h = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/offerings",
            201,
            self.token_a,
            {
                "name": "Paket Pasang Komputer",
                "offering_type": "hybrid",
                "unit_price_idr": 500000,
                "unit": "paket",
                "service_cost_idr": 100000,
            },
        )
        hybrid = res_h["item"]
        self.assertTrue(hybrid["requires_stock_movement"])
        # Stock not purchased yet, but service cost is 100000
        self.assertEqual(hybrid["cost_status"], "known")
        self.assertEqual(hybrid["unit_cost_idr"], 100000)
        self.assertEqual(hybrid["cost_source"], "service_input")
        self.assertEqual(hybrid["margin_idr"], 400000)
        self.assertEqual(hybrid["margin_pct"], 80.0)

        # Purchase inventory for goods: WA cost becomes known
        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/purchases",
            201,
            self.token_a,
            {"offering_id": goods["offering_id"], "qty": "10", "total_cost_idr": 90000},
        )
        # Fetch updated goods offering
        res_g_updated = self.request(
            "GET",
            f"/v1/workspaces/{self.ws_a}/offerings/{goods['offering_id']}",
            200,
            self.token_a,
        )
        g_item = res_g_updated["item"]
        self.assertEqual(g_item["cost_status"], "known")
        self.assertEqual(g_item["unit_cost_idr"], 9000)
        self.assertEqual(g_item["cost_source"], "inventory_wa")
        self.assertEqual(g_item["margin_idr"], 6000)  # 15000 - 9000
        self.assertEqual(g_item["margin_pct"], 40.0)

        # Purchase inventory for hybrid: now combines WA + service cost
        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/purchases",
            201,
            self.token_a,
            {"offering_id": hybrid["offering_id"], "qty": "5", "total_cost_idr": 1000000},
        )
        res_h_updated = self.request(
            "GET",
            f"/v1/workspaces/{self.ws_a}/offerings/{hybrid['offering_id']}",
            200,
            self.token_a,
        )
        h_item = res_h_updated["item"]
        self.assertEqual(h_item["cost_status"], "known")
        self.assertEqual(h_item["wa_unit_cost_idr"], 200000)
        self.assertEqual(h_item["service_cost_idr"], 100000)
        self.assertEqual(h_item["unit_cost_idr"], 300000)  # 200000 + 100000
        self.assertEqual(h_item["cost_source"], "hybrid")
        self.assertEqual(h_item["margin_idr"], 200000)  # 500000 - 300000
        self.assertEqual(h_item["margin_pct"], 40.0)

    def test_pricing_decisions_and_issue_33_invariance(self):
        # Create goods offering at Rp 10.000
        off = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/offerings",
            201,
            self.token_a,
            {"name": "Kecap Manis", "offering_type": "goods", "unit_price_idr": 10000, "unit": "botol"},
        )["item"]
        off_id = off["offering_id"]

        # Purchase 10 botol @ Rp 60.000 (unit cost Rp 6.000)
        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/purchases",
            201,
            self.token_a,
            {"offering_id": off_id, "qty": "10", "total_cost_idr": 60000, "occurred_at": "2026-11-28T08:00:00+07:00"},
        )

        # Record Sale 1 at old price (2 botol @ 10.000 = 20.000)
        sale1 = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/sales",
            201,
            self.token_a,
            {"lines": [{"offering_id": off_id, "qty": "2"}], "occurred_at": "2026-11-28T09:00:00+07:00"},
        )["item"]
        self.assertEqual(sale1["total_revenue_idr"], 20000)

        # Save Pricing Decision: change price to Rp 15.000
        decision_payload = {
            "new_price_idr": 15000,
            "strategy_notes": "Kenaikan harga kedelai nasional",
        }
        res_dec = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/offerings/{off_id}/pricing",
            200,
            self.token_a,
            decision_payload,
        )
        dec = res_dec["item"]["decision"]
        updated_off = res_dec["item"]["offering"]
        self.assertEqual(dec["previous_price_idr"], 10000)
        self.assertEqual(dec["new_price_idr"], 15000)
        self.assertEqual(dec["unit_cost_idr"], 6000)
        self.assertEqual(dec["cost_status"], "known")
        self.assertEqual(dec["margin_idr"], 9000)
        self.assertEqual(dec["margin_pct"], 60.0)
        self.assertEqual(dec["strategy_notes"], "Kenaikan harga kedelai nasional")
        self.assertEqual(updated_off["unit_price_idr"], 15000)

        # Query pricing decisions audit trail
        decisions_list = self.request(
            "GET",
            f"/v1/workspaces/{self.ws_a}/offerings/{off_id}/pricing-decisions",
            200,
            self.token_a,
        )["items"]
        self.assertEqual(len(decisions_list), 1)
        self.assertEqual(decisions_list[0]["decision_id"], dec["decision_id"])

        # Record Sale 2 at new price (3 botol @ 15.000 = 45.000)
        sale2 = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/sales",
            201,
            self.token_a,
            {"lines": [{"offering_id": off_id, "qty": "3"}], "occurred_at": "2026-11-28T10:00:00+07:00"},
        )["item"]
        self.assertEqual(sale2["total_revenue_idr"], 45000)

        # ISSUE #33 CRITICAL INVARIANCE:
        # Check that Sale 1 historical revenue is STILL 20.000!
        with db_transaction(self.db_path) as conn:
            s1_db = conn.execute("SELECT total_revenue_idr FROM sales WHERE sale_id = ?", (sale1["sale_id"],)).fetchone()
            self.assertEqual(s1_db[0], 20000)
            l1_db = conn.execute("SELECT revenue_idr FROM sale_lines WHERE sale_id = ?", (sale1["sale_id"],)).fetchone()
            self.assertEqual(l1_db[0], 20000)

        # Daily report aggregates accurately reflect both transactions
        report = self.request(
            "GET",
            f"/v1/workspaces/{self.ws_a}/reports/daily?date=2026-11-28",
            200,
            self.token_a,
        )["report"]
        self.assertEqual(report["revenue_idr"], 65000)  # 20.000 + 45.000

    def test_archive_and_unarchive_flow(self):
        # Create offering
        off = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/offerings",
            201,
            self.token_a,
            {"name": "Es Teh Manis", "offering_type": "goods", "unit_price_idr": 5000, "unit": "gelas"},
        )["item"]
        off_id = off["offering_id"]

        # Purchase inventory
        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/purchases",
            201,
            self.token_a,
            {"offering_id": off_id, "qty": "20", "total_cost_idr": 40000},
        )

        # Record a past sale before archiving
        past_sale = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/sales",
            201,
            self.token_a,
            {"lines": [{"offering_id": off_id, "qty": "2"}]},
        )["item"]
        self.assertEqual(past_sale["total_revenue_idr"], 10000)

        # 1. Archive offering
        archived = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/offerings/{off_id}/archive",
            200,
            self.token_a,
        )["item"]
        self.assertTrue(archived["is_archived"])
        self.assertIsNotNone(archived["archived_at"])
        self.assertEqual(archived["status"], "archived")

        # 2. Filter list by status
        active_list = self.request(
            "GET",
            f"/v1/workspaces/{self.ws_a}/offerings?status=active",
            200,
            self.token_a,
        )["items"]
        self.assertNotIn(off_id, [o["offering_id"] for o in active_list])

        archived_list = self.request(
            "GET",
            f"/v1/workspaces/{self.ws_a}/offerings?status=archived",
            200,
            self.token_a,
        )["items"]
        self.assertIn(off_id, [o["offering_id"] for o in archived_list])

        # 3. Guard: new sale with archived offering MUST fail with 422
        res_sale_err = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/sales",
            422,
            self.token_a,
            {"lines": [{"offering_id": off_id, "qty": "1"}]},
        )
        self.assertEqual(res_sale_err["code"], "offering_archived")

        # 4. Guard: new purchase with archived offering MUST fail with 422
        res_pur_err = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/purchases",
            422,
            self.token_a,
            {"offering_id": off_id, "qty": "5", "total_cost_idr": 10000},
        )
        self.assertEqual(res_pur_err["code"], "offering_archived")

        # 5. Historical transaction report remains valid and readable
        report = self.request(
            "GET",
            f"/v1/workspaces/{self.ws_a}/reports/daily",
            200,
            self.token_a,
        )["report"]
        self.assertEqual(report["revenue_idr"], 10000)
        drill_sale = report["drill_down"]["sales"][0]
        self.assertEqual(drill_sale["lines"][0]["offering_name"], "Es Teh Manis")
        self.assertEqual(drill_sale["lines"][0]["unit"], "gelas")

        # 6. Unarchive offering
        unarchived = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/offerings/{off_id}/unarchive",
            200,
            self.token_a,
        )["item"]
        self.assertFalse(unarchived["is_archived"])
        self.assertIsNone(unarchived["archived_at"])
        self.assertEqual(unarchived["status"], "active")

        # 7. New sale works again after unarchiving
        new_sale = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/sales",
            201,
            self.token_a,
            {"lines": [{"offering_id": off_id, "qty": "1"}]},
        )["item"]
        self.assertEqual(new_sale["total_revenue_idr"], 5000)

    def test_tenant_isolation(self):
        off_a = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/offerings",
            201,
            self.token_a,
            {"name": "Produk Rahasia A", "offering_type": "goods", "unit_price_idr": 25000},
        )["item"]
        off_a_id = off_a["offering_id"]

        # Actor B cannot access, archive, unarchive, or change pricing of Actor A's offering
        self.request("GET", f"/v1/workspaces/{self.ws_a}/offerings", 404, self.token_b)
        self.request("GET", f"/v1/workspaces/{self.ws_a}/offerings/{off_a_id}", 404, self.token_b)
        self.request("POST", f"/v1/workspaces/{self.ws_a}/offerings/{off_a_id}/archive", 404, self.token_b)
        self.request("POST", f"/v1/workspaces/{self.ws_a}/offerings/{off_a_id}/unarchive", 404, self.token_b)
        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/offerings/{off_a_id}/pricing",
            404,
            self.token_b,
            {"new_price_idr": 99999},
        )
        self.request("GET", f"/v1/workspaces/{self.ws_a}/offerings/{off_a_id}/pricing-decisions", 404, self.token_b)

        # Unauthenticated requests return 401
        self.request("GET", f"/v1/workspaces/{self.ws_a}/offerings", 401)
        self.request("POST", f"/v1/workspaces/{self.ws_a}/offerings/{off_a_id}/archive", 401)
        self.request("POST", f"/v1/workspaces/{self.ws_a}/offerings/{off_a_id}/pricing", 401, payload={"new_price_idr": 100})


if __name__ == "__main__":
    unittest.main()
