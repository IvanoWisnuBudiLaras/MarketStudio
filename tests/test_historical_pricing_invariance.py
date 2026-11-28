"""Unit and integration tests for Issue #33: Invariance of historical sales transactions when catalog prices change.

Refs #33 / Closes #33.
TEST-BUS-01: 'perubahan harga tidak mengubah sale lama'.
"""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app.db import db_transaction
from app.server import create_server


class HistoricalPricingInvarianceTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.db_path = str(Path(directory) / "test_histori_harga.sqlite3")
        server = create_server(port=0, db_path=self.db_path)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_port}"

        self.token = self.login("actor_a", "dev-a-pass")
        self.ws_id = self.create_workspace(self.token, "Warung Invariansi Harga")

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

    def test_primary_scenario_goods_price_change_invariance(self):
        """Skenario Utama Issue #33:

        1. Buat offering awal dengan harga Rp10.000.
        2. Catat transaksi penjualan awal (Sale 1) @ Rp10.000 (qty 2 -> Rp20.000).
        3. Ubah harga jual offering di katalog / pricing decision menjadi Rp15.000.
        4. Catat transaksi penjualan baru (Sale 2) @ Rp15.000 (qty 3 -> Rp45.000).
        5. Verifikasi Invariansi Harga Historis:
           - Detail line item Sale 1 dan total revenue Sale 1 di DB dan API tetap Rp20.000.
           - Laporan harian merefleksikan Sale 1 (Rp20.000) + Sale 2 (Rp45.000) = Rp65.000.
           - Transaksi Sale 2 memakai harga baru (Rp45.000).
        """
        # 1. Offering awal Rp10.000
        off = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/offerings",
            201,
            self.token,
            {"name": "Minyak Goreng 1L", "offering_type": "goods", "unit_price_idr": 10000, "unit": "pouch"},
        )["item"]
        off_id = off["offering_id"]

        # Purchase inventory (10 pouch @ Rp7.000 = Rp70.000)
        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/purchases",
            201,
            self.token,
            {"offering_id": off_id, "qty": "10", "total_cost_idr": 70000, "occurred_at": "2026-11-28T08:00:00+07:00"},
        )

        # 2. Sale 1 pada harga lama: 2 pouch @ Rp10.000 = Rp20.000
        sale1 = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/sales",
            201,
            self.token,
            {"lines": [{"offering_id": off_id, "qty": "2"}], "occurred_at": "2026-11-28T09:00:00+07:00"},
        )["item"]
        self.assertEqual(sale1["total_revenue_idr"], 20000)
        self.assertEqual(len(sale1["lines"]), 1)
        self.assertEqual(sale1["lines"][0]["revenue_idr"], 20000)

        # 3. Ubah harga offering di katalog via pricing decision menjadi Rp15.000
        decision_payload = {
            "new_price_idr": 15000,
            "strategy_notes": "Penyesuaian HET minyak goreng pemerintah",
        }
        res_dec = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/offerings/{off_id}/pricing",
            200,
            self.token,
            decision_payload,
        )
        dec = res_dec["item"]["decision"]
        updated_off = res_dec["item"]["offering"]
        self.assertEqual(dec["previous_price_idr"], 10000)
        self.assertEqual(dec["new_price_idr"], 15000)
        self.assertEqual(updated_off["unit_price_idr"], 15000)

        # Verify offering GET returns new price
        get_off = self.request("GET", f"/v1/workspaces/{self.ws_id}/offerings/{off_id}", 200, self.token)["item"]
        self.assertEqual(get_off["unit_price_idr"], 15000)

        # 4. Sale 2 pada harga baru: 3 pouch @ Rp15.000 = Rp45.000
        sale2 = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/sales",
            201,
            self.token,
            {"lines": [{"offering_id": off_id, "qty": "3"}], "occurred_at": "2026-11-28T10:00:00+07:00"},
        )["item"]
        self.assertEqual(sale2["total_revenue_idr"], 45000)
        self.assertEqual(len(sale2["lines"]), 1)
        self.assertEqual(sale2["lines"][0]["revenue_idr"], 45000)

        # 5. VERIFIKASI INVARIANSI HISTORIS

        # A. Database Direct Invariance
        with db_transaction(self.db_path) as conn:
            # Sale 1 table row
            s1_db = conn.execute("SELECT total_revenue_idr FROM sales WHERE sale_id = ?", (sale1["sale_id"],)).fetchone()
            self.assertEqual(s1_db["total_revenue_idr"], 20000)

            # Sale 1 line items
            l1_db = conn.execute("SELECT revenue_idr, qty FROM sale_lines WHERE sale_id = ?", (sale1["sale_id"],)).fetchone()
            self.assertEqual(l1_db["revenue_idr"], 20000)
            self.assertEqual(l1_db["qty"], "2")

            # Sale 1 cash movement
            c1_db = conn.execute("SELECT amount_idr, direction FROM cash_movements WHERE reference_id = ?", (sale1["sale_id"],)).fetchone()
            self.assertEqual(c1_db["amount_idr"], 20000)
            self.assertEqual(c1_db["direction"], "in")

            # Sale 2 table row
            s2_db = conn.execute("SELECT total_revenue_idr FROM sales WHERE sale_id = ?", (sale2["sale_id"],)).fetchone()
            self.assertEqual(s2_db["total_revenue_idr"], 45000)

            # Sale 2 line items
            l2_db = conn.execute("SELECT revenue_idr, qty FROM sale_lines WHERE sale_id = ?", (sale2["sale_id"],)).fetchone()
            self.assertEqual(l2_db["revenue_idr"], 45000)
            self.assertEqual(l2_db["qty"], "3")

            # Sale 2 cash movement
            c2_db = conn.execute("SELECT amount_idr, direction FROM cash_movements WHERE reference_id = ?", (sale2["sale_id"],)).fetchone()
            self.assertEqual(c2_db["amount_idr"], 45000)

        # B. API Daily Report Invariance
        report = self.request(
            "GET",
            f"/v1/workspaces/{self.ws_id}/reports/daily?date=2026-11-28",
            200,
            self.token,
        )["report"]

        # Aggregate revenue: 20.000 + 45.000 = 65.000
        self.assertEqual(report["revenue_idr"], 65000)
        self.assertEqual(report["cash_in_idr"], 65000)

        # Drill-down sales items
        sales_in_drill = {s["sale_id"]: s for s in report["drill_down"]["sales"]}
        self.assertIn(sale1["sale_id"], sales_in_drill)
        self.assertIn(sale2["sale_id"], sales_in_drill)

        # Sale 1 in API drill-down retains original revenue
        drill_s1 = sales_in_drill[sale1["sale_id"]]
        self.assertEqual(drill_s1["total_revenue_idr"], 20000)
        self.assertEqual(drill_s1["lines"][0]["revenue_idr"], 20000)

        # Sale 2 in API drill-down uses new price
        drill_s2 = sales_in_drill[sale2["sale_id"]]
        self.assertEqual(drill_s2["total_revenue_idr"], 45000)
        self.assertEqual(drill_s2["lines"][0]["revenue_idr"], 45000)

    def test_multi_date_historical_daily_reports_remain_isolated_and_invariant(self):
        """Verifikasi bahwa laporan harian masa lalu tidak terdistorsi saat harga katalog diubah di hari berikutnya."""
        off = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/offerings",
            201,
            self.token,
            {"name": "Beras Premium 5kg", "offering_type": "goods", "unit_price_idr": 65000, "unit": "karung"},
        )["item"]
        off_id = off["offering_id"]

        # Purchase 20 karung @ Rp50.000
        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/purchases",
            201,
            self.token,
            {"offering_id": off_id, "qty": "20", "total_cost_idr": 1000000, "occurred_at": "2026-11-20T08:00:00+07:00"},
        )

        # Day 1: Sale 1 (2 karung @ Rp65.000 = Rp130.000)
        s1 = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/sales",
            201,
            self.token,
            {"lines": [{"offering_id": off_id, "qty": "2"}], "occurred_at": "2026-11-20T14:30:00+07:00"},
        )["item"]
        self.assertEqual(s1["total_revenue_idr"], 130000)

        # Query Day 1 report BEFORE price update
        rep1_before = self.request(
            "GET",
            f"/v1/workspaces/{self.ws_id}/reports/daily?date=2026-11-20",
            200,
            self.token,
        )["report"]
        self.assertEqual(rep1_before["revenue_idr"], 130000)
        self.assertEqual(rep1_before["cash_in_idr"], 130000)

        # Day 2: Catalog price increases to Rp75.000
        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/offerings/{off_id}/pricing",
            200,
            self.token,
            {"new_price_idr": 75000, "strategy_notes": "Kenaikan harga gabah kering giling"},
        )

        # Day 2: Sale 2 (3 karung @ Rp75.000 = Rp225.000)
        s2 = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/sales",
            201,
            self.token,
            {"lines": [{"offering_id": off_id, "qty": "3"}], "occurred_at": "2026-11-21T10:15:00+07:00"},
        )["item"]
        self.assertEqual(s2["total_revenue_idr"], 225000)

        # Day 1 report AFTER price update MUST be byte-for-byte financial invariant!
        rep1_after = self.request(
            "GET",
            f"/v1/workspaces/{self.ws_id}/reports/daily?date=2026-11-20",
            200,
            self.token,
        )["report"]
        self.assertEqual(rep1_after["revenue_idr"], 130000)
        self.assertEqual(rep1_after["cash_in_idr"], 130000)
        self.assertEqual(rep1_after["drill_down"]["sales"][0]["total_revenue_idr"], 130000)
        self.assertEqual(rep1_after["drill_down"]["sales"][0]["lines"][0]["revenue_idr"], 130000)

        # Day 2 report reflects only Day 2 transaction at new price
        rep2 = self.request(
            "GET",
            f"/v1/workspaces/{self.ws_id}/reports/daily?date=2026-11-21",
            200,
            self.token,
        )["report"]
        self.assertEqual(rep2["revenue_idr"], 225000)
        self.assertEqual(rep2["cash_in_idr"], 225000)
        self.assertEqual(rep2["drill_down"]["sales"][0]["total_revenue_idr"], 225000)
        self.assertEqual(rep2["drill_down"]["sales"][0]["lines"][0]["revenue_idr"], 225000)

    def test_service_and_hybrid_offerings_price_changes_preserve_history(self):
        """Verifikasi invariansi pada offering bertipe service (jasa murni) dan hybrid."""
        # 1. Service offering
        svc = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/offerings",
            201,
            self.token,
            {"name": "Jasa Servis Motor", "offering_type": "service", "unit_price_idr": 50000, "service_cost_idr": 20000, "unit": "motor"},
        )["item"]
        svc_id = svc["offering_id"]

        # 2. Goods for hybrid
        oli = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/offerings",
            201,
            self.token,
            {"name": "Oli Mesin Sintetis", "offering_type": "goods", "unit_price_idr": 70000, "unit": "botol"},
        )["item"]
        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/purchases",
            201,
            self.token,
            {"offering_id": oli["offering_id"], "qty": "10", "total_cost_idr": 500000, "occurred_at": "2026-11-28T08:00:00+07:00"},
        )

        # 3. Hybrid offering
        hyb = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/offerings",
            201,
            self.token,
            {"name": "Paket Tune Up & Oli", "offering_type": "hybrid", "unit_price_idr": 120000, "service_cost_idr": 30000, "unit": "paket"},
        )["item"]
        hyb_id = hyb["offering_id"]
        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/purchases",
            201,
            self.token,
            {"offering_id": hyb_id, "qty": "5", "total_cost_idr": 250000, "occurred_at": "2026-11-28T08:30:00+07:00"},
        )

        # Sale 1: 1 Jasa Servis @ Rp50.000 + 1 Paket Tune Up @ Rp120.000 = Rp170.000
        sale1 = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/sales",
            201,
            self.token,
            {
                "lines": [
                    {"offering_id": svc_id, "qty": "1"},
                    {"offering_id": hyb_id, "qty": "1"},
                ],
                "occurred_at": "2026-11-28T09:00:00+07:00",
            },
        )["item"]
        self.assertEqual(sale1["total_revenue_idr"], 170000)

        # Update pricing for both Service and Hybrid
        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/offerings/{svc_id}/pricing",
            200,
            self.token,
            {"new_price_idr": 75000, "service_cost_idr": 25000, "strategy_notes": "Kenaikan keahlian teknisi"},
        )
        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/offerings/{hyb_id}/pricing",
            200,
            self.token,
            {"new_price_idr": 160000, "service_cost_idr": 40000, "strategy_notes": "Kenaikan harga paket komplit"},
        )

        # Sale 2: 2 Jasa Servis @ Rp75.000 (=150.000) + 1 Paket Tune Up @ Rp160.000 = Rp310.000
        sale2 = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/sales",
            201,
            self.token,
            {
                "lines": [
                    {"offering_id": svc_id, "qty": "2"},
                    {"offering_id": hyb_id, "qty": "1"},
                ],
                "occurred_at": "2026-11-28T11:00:00+07:00",
            },
        )["item"]
        self.assertEqual(sale2["total_revenue_idr"], 310000)

        # Invariance assertion
        with db_transaction(self.db_path) as conn:
            # Sale 1 lines must still have 50.000 and 120.000
            s1_lines = conn.execute(
                "SELECT offering_id, qty, revenue_idr FROM sale_lines WHERE sale_id = ? ORDER BY revenue_idr ASC",
                (sale1["sale_id"],),
            ).fetchall()
            self.assertEqual(s1_lines[0]["offering_id"], svc_id)
            self.assertEqual(s1_lines[0]["revenue_idr"], 50000)
            self.assertEqual(s1_lines[1]["offering_id"], hyb_id)
            self.assertEqual(s1_lines[1]["revenue_idr"], 120000)

            # Sale 2 lines must reflect new prices
            s2_lines = conn.execute(
                "SELECT offering_id, qty, revenue_idr FROM sale_lines WHERE sale_id = ? ORDER BY revenue_idr ASC",
                (sale2["sale_id"],),
            ).fetchall()
            self.assertEqual(s2_lines[0]["offering_id"], svc_id)
            self.assertEqual(s2_lines[0]["revenue_idr"], 150000)  # 2 * 75000
            self.assertEqual(s2_lines[1]["offering_id"], hyb_id)
            self.assertEqual(s2_lines[1]["revenue_idr"], 160000)  # 1 * 160000

        # Daily report sum: 170.000 + 310.000 = 480.000
        rep = self.request("GET", f"/v1/workspaces/{self.ws_id}/reports/daily?date=2026-11-28", 200, self.token)["report"]
        self.assertEqual(rep["revenue_idr"], 480000)

    def test_multiple_successive_price_steps_escalation_and_reduction(self):
        """Verifikasi bahwa perubahan harga berulang kali (naik, turun, naik lagi)

        tetap mempertahankan harga transaksi historis pada setiap titik waktu.
        """
        off = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/offerings",
            201,
            self.token,
            {"name": "Gula Pasir 1kg", "offering_type": "goods", "unit_price_idr": 12000, "unit": "kg"},
        )["item"]
        off_id = off["offering_id"]

        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/purchases",
            201,
            self.token,
            {"offering_id": off_id, "qty": "50", "total_cost_idr": 400000},
        )

        # Step 1: price = 12.000 -> Sale 1 (1 kg @ 12.000 = 12.000)
        s1 = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/sales",
            201,
            self.token,
            {"lines": [{"offering_id": off_id, "qty": "1"}]},
        )["item"]
        self.assertEqual(s1["total_revenue_idr"], 12000)

        # Step 2: increase price to 18.000 -> Sale 2 (2 kg @ 18.000 = 36.000)
        self.request("POST", f"/v1/workspaces/{self.ws_id}/offerings/{off_id}/pricing", 200, self.token, {"new_price_idr": 18000})
        s2 = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/sales",
            201,
            self.token,
            {"lines": [{"offering_id": off_id, "qty": "2"}]},
        )["item"]
        self.assertEqual(s2["total_revenue_idr"], 36000)

        # Step 3: decrease price to 15.000 -> Sale 3 (3 kg @ 15.000 = 45.000)
        self.request("POST", f"/v1/workspaces/{self.ws_id}/offerings/{off_id}/pricing", 200, self.token, {"new_price_idr": 15000})
        s3 = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/sales",
            201,
            self.token,
            {"lines": [{"offering_id": off_id, "qty": "3"}]},
        )["item"]
        self.assertEqual(s3["total_revenue_idr"], 45000)

        # Step 4: increase price to 25.000 -> Sale 4 (4 kg @ 25.000 = 100.000)
        self.request("POST", f"/v1/workspaces/{self.ws_id}/offerings/{off_id}/pricing", 200, self.token, {"new_price_idr": 25000})
        s4 = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/sales",
            201,
            self.token,
            {"lines": [{"offering_id": off_id, "qty": "4"}]},
        )["item"]
        self.assertEqual(s4["total_revenue_idr"], 100000)

        # All 4 sales MUST retain their exact respective revenues
        with db_transaction(self.db_path) as conn:
            revs = {
                row["sale_id"]: row["total_revenue_idr"]
                for row in conn.execute("SELECT sale_id, total_revenue_idr FROM sales").fetchall()
            }
            self.assertEqual(revs[s1["sale_id"]], 12000)
            self.assertEqual(revs[s2["sale_id"]], 36000)
            self.assertEqual(revs[s3["sale_id"]], 45000)
            self.assertEqual(revs[s4["sale_id"]], 100000)

        # Total revenue in daily report = 12.000 + 36.000 + 45.000 + 100.000 = 193.000
        rep = self.request("GET", f"/v1/workspaces/{self.ws_id}/reports/daily", 200, self.token)["report"]
        self.assertEqual(rep["revenue_idr"], 193000)

    def test_custom_line_price_override_remains_invariant_under_catalog_changes(self):
        """Ketika kasir/operator menetapkan harga khusus (total_price_idr manual),

        nilai tersebut harus tetap kekal dan tidak terpengaruh oleh harga katalog lama maupun baru.
        """
        off = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/offerings",
            201,
            self.token,
            {"name": "Kopi Bubuk 250g", "offering_type": "goods", "unit_price_idr": 30000, "unit": "bungkus"},
        )["item"]
        off_id = off["offering_id"]

        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/purchases",
            201,
            self.token,
            {"offering_id": off_id, "qty": "10", "total_cost_idr": 150000},
        )

        # Sale dengan override total_price_idr (diskon khusus pelanggan tetap: 2 bungkus normal 60.000 -> 50.000)
        s_override = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/sales",
            201,
            self.token,
            {"lines": [{"offering_id": off_id, "qty": "2", "total_price_idr": 50000}]},
        )["item"]
        self.assertEqual(s_override["total_revenue_idr"], 50000)
        self.assertEqual(s_override["lines"][0]["revenue_idr"], 50000)

        # Catalog price updated to Rp40.000
        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/offerings/{off_id}/pricing",
            200,
            self.token,
            {"new_price_idr": 40000, "strategy_notes": "Kenaikan harga biji kopi robusta"},
        )

        # Historical sale with manual override remains exactly 50.000
        with db_transaction(self.db_path) as conn:
            db_sale = conn.execute("SELECT total_revenue_idr FROM sales WHERE sale_id = ?", (s_override["sale_id"],)).fetchone()
            self.assertEqual(db_sale["total_revenue_idr"], 50000)
            db_line = conn.execute("SELECT revenue_idr FROM sale_lines WHERE sale_id = ?", (s_override["sale_id"],)).fetchone()
            self.assertEqual(db_line["revenue_idr"], 50000)

        rep = self.request("GET", f"/v1/workspaces/{self.ws_id}/reports/daily", 200, self.token)["report"]
        self.assertEqual(rep["revenue_idr"], 50000)

    def test_mixed_basket_and_archiving_after_price_change_preserves_historical_invariance(self):
        """Verifikasi keranjang multi-item dan pengarsipan offering setelah perubahan harga."""
        # 1. Offering A (goods)
        off_a = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/offerings",
            201,
            self.token,
            {"name": "Sabun Mandi", "offering_type": "goods", "unit_price_idr": 5000, "unit": "batang"},
        )["item"]
        off_a_id = off_a["offering_id"]
        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/purchases",
            201,
            self.token,
            {"offering_id": off_a_id, "qty": "20", "total_cost_idr": 60000, "occurred_at": "2026-11-28T08:00:00+07:00"},
        )

        # 2. Offering B (goods)
        off_b = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/offerings",
            201,
            self.token,
            {"name": "Sikat Gigi", "offering_type": "goods", "unit_price_idr": 8000, "unit": "pcs"},
        )["item"]
        off_b_id = off_b["offering_id"]
        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/purchases",
            201,
            self.token,
            {"offering_id": off_b_id, "qty": "15", "total_cost_idr": 60000, "occurred_at": "2026-11-28T08:30:00+07:00"},
        )

        # Sale 1 (Mixed basket): 2 Sabun (@ 5.000 = 10.000) + 1 Sikat Gigi (@ 8.000 = 8.000) = 18.000
        sale1 = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/sales",
            201,
            self.token,
            {
                "lines": [
                    {"offering_id": off_a_id, "qty": "2"},
                    {"offering_id": off_b_id, "qty": "1"},
                ],
                "occurred_at": "2026-11-28T09:00:00+07:00",
            },
        )["item"]
        self.assertEqual(sale1["total_revenue_idr"], 18000)

        # Change price of Sabun Mandi to Rp 7.500 (Sikat Gigi remains Rp 8.000)
        self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/offerings/{off_a_id}/pricing",
            200,
            self.token,
            {"new_price_idr": 7500, "strategy_notes": "Kenaikan harga sabun"},
        )

        # Sale 2: 2 Sabun (@ 7.500 = 15.000) + 2 Sikat Gigi (@ 8.000 = 16.000) = 31.000
        sale2 = self.request(
            "POST",
            f"/v1/workspaces/{self.ws_id}/sales",
            201,
            self.token,
            {
                "lines": [
                    {"offering_id": off_a_id, "qty": "2"},
                    {"offering_id": off_b_id, "qty": "2"},
                ],
                "occurred_at": "2026-11-28T10:00:00+07:00",
            },
        )["item"]
        self.assertEqual(sale2["total_revenue_idr"], 31000)

        # Archive Sabun Mandi
        self.request("POST", f"/v1/workspaces/{self.ws_id}/offerings/{off_a_id}/archive", 200, self.token)

        # Verifikasi bahwa Sale 1 dan Sale 2 tetap tidak berubah di DB
        with db_transaction(self.db_path) as conn:
            s1_db = conn.execute("SELECT total_revenue_idr FROM sales WHERE sale_id = ?", (sale1["sale_id"],)).fetchone()
            self.assertEqual(s1_db["total_revenue_idr"], 18000)
            s2_db = conn.execute("SELECT total_revenue_idr FROM sales WHERE sale_id = ?", (sale2["sale_id"],)).fetchone()
            self.assertEqual(s2_db["total_revenue_idr"], 31000)

            # Lines check
            lines1 = {
                row["offering_id"]: row["revenue_idr"]
                for row in conn.execute(
                    "SELECT offering_id, revenue_idr FROM sale_lines WHERE sale_id = ?",
                    (sale1["sale_id"],),
                ).fetchall()
            }
            self.assertEqual(lines1[off_a_id], 10000)
            self.assertEqual(lines1[off_b_id], 8000)

        # Verifikasi laporan harian tetap mencerminkan omzet 18.000 + 31.000 = 49.000
        rep = self.request("GET", f"/v1/workspaces/{self.ws_id}/reports/daily?date=2026-11-28", 200, self.token)["report"]
        self.assertEqual(rep["revenue_idr"], 49000)


if __name__ == "__main__":
    unittest.main()
