"""Tests for Issue #46: Market Price Benchmark (attributed snapshot + manual fallback)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from app.db import db_transaction, init_db
from app.server import create_server
from app.service import BaselineService


class PriceBenchmarkTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["MARKETSTUDIO_QUIET_LOGS"] = "1"
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "bench_test.sqlite3")
        init_db(self.db_path)
        self.service = BaselineService(self.db_path)
        self.server = create_server(host="127.0.0.1", port=0, db_path=self.db_path)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        self.token_a = self.service.create_session("actor_a", "dev-a-pass")["token"]
        self.token_b = self.service.create_session("actor_b", "dev-b-pass")["token"]

        _, ws_a = self.service.create_workspace(
            {"name": "Toko Beras A", "business_type": "retail", "mode": "goods"},
            actor="actor_a",
        )
        self.ws_a = ws_a["workspace_id"]

        _, ws_b = self.service.create_workspace(
            {"name": "Toko B", "business_type": "retail", "mode": "goods"},
            actor="actor_b",
        )
        self.ws_b = ws_b["workspace_id"]

        _, off_kg = self.service.create_offering(
            self.ws_a,
            actor_id="actor_a",
            payload={
                "name": "Beras Premium 1kg",
                "offering_type": "goods",
                "unit": "kg",
                "unit_price_idr": 15000,
                "requires_stock_movement": True,
            },
            actor="actor_a",
        )
        self.off_kg = off_kg["offering_id"]

        _, off_sesi = self.service.create_offering(
            self.ws_a,
            actor_id="actor_a",
            payload={
                "name": "Konsultasi Bisnis",
                "offering_type": "service",
                "unit": "sesi",
                "unit_price_idr": 100000,
                "requires_stock_movement": False,
            },
            actor="actor_a",
        )
        self.off_sesi = off_sesi["offering_id"]

        _, off_b = self.service.create_offering(
            self.ws_b,
            actor_id="actor_b",
            payload={
                "name": "Beras B",
                "offering_type": "goods",
                "unit": "kg",
                "unit_price_idr": 14000,
                "requires_stock_movement": True,
            },
            actor="actor_b",
        )
        self.off_b = off_b["offering_id"]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmpdir.cleanup()

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        token: str | None = None,
    ) -> tuple[int, dict]:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        raw = None
        if body is not None:
            raw = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=raw, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        return resp.status, data

    def test_attributed_snapshot_list_and_exact_unit_compare(self) -> None:
        status, snaps = self._request(
            "GET",
            f"/v1/workspaces/{self.ws_a}/price-benchmarks/snapshots",
            token=self.token_a,
        )
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(snaps["items"]), 4)
        official = snaps["items"][0]
        self.assertEqual(official["snapshot_id"], "bapanas_beras_medium_maret_2026")
        self.assertEqual(official["source_kind"], "transcribed_official")
        self.assertFalse(official["is_synthetic"])
        self.assertTrue(official["is_historical"])

        first = snaps["items"][1]
        self.assertEqual(first["source_kind"], "synthetic_demo")
        self.assertTrue(first["is_synthetic"])
        self.assertIsNone(first["source_url"])
        self.assertEqual(first["currency"], "IDR")
        self.assertIn("Demo sintetis", first["evidence_note"])

        status, res = self._request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/price-benchmarks/compare",
            body={
                "offering_id": self.off_kg,
                "source_kind": "synthetic_demo",
                "snapshot_id": "demo_beras_medium_jkt",
            },
            token=self.token_a,
        )
        self.assertEqual(status, 200)
        item = res["item"]
        self.assertTrue(item["comparable"])
        self.assertTrue(item["read_only"])
        self.assertTrue(item["catalog_unchanged"])
        self.assertEqual(item["offering_unit"], "kg")
        self.assertEqual(item["offering_unit_price_idr"], 15000)
        self.assertEqual(item["normalized_benchmark_price_idr"], 13500)
        self.assertEqual(item["price_delta_idr"], 1500)
        self.assertEqual(item["price_delta_percent"], "11.11")
        self.assertEqual(item["observation"]["source_kind"], "synthetic_demo")
        self.assertTrue(item["observation"]["is_synthetic"])
        self.assertIsNone(item["observation"]["source_url"])
        self.assertIn("Demo sintetis", item["observation"]["evidence_note"])

    def test_metric_unit_conversion_g_to_kg(self) -> None:
        # bapanas_gula_pasir_500g_jkt is Rp 9.000 per 500 g -> Rp 18.000 per kg
        status, res = self._request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/price-benchmarks/compare",
            body={
                "offering_id": self.off_kg,
                "source_kind": "synthetic_demo",
                "snapshot_id": "demo_gula_pasir_500g_jkt",
            },
            token=self.token_a,
        )
        self.assertEqual(status, 200)
        item = res["item"]
        self.assertEqual(item["normalized_benchmark_price_idr"], 18000)
        self.assertEqual(item["price_delta_idr"], -3000)
        self.assertEqual(item["price_delta_percent"], "-16.67")

    def test_incomparable_units_rejected_422(self) -> None:
        status, res = self._request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/price-benchmarks/compare",
            body={
                "offering_id": self.off_sesi,
                "source_kind": "synthetic_demo",
                "snapshot_id": "demo_beras_medium_jkt",
            },
            token=self.token_a,
        )
        self.assertEqual(status, 422)
        self.assertEqual(res["code"], "incomparable_units")

    def test_manual_fallback_with_provenance_and_validation(self) -> None:
        status, res = self._request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/price-benchmarks/compare",
            body={
                "offering_id": self.off_kg,
                "source_kind": "manual_fallback",
                "source_label": "Survei Pasar Baru",
                "evidence_note": "Foto papan harga kios #12",
                "observed_at": "2026-11-27",
                "location_market": "Pasar Baru, Bandung",
                "unit": "g",
                "quantity": "250",
                "currency": "IDR",
                "observed_price_idr": 3500,
            },
            token=self.token_a,
        )
        self.assertEqual(status, 200)
        item = res["item"]
        self.assertEqual(item["normalized_benchmark_price_idr"], 14000)
        self.assertEqual(item["price_delta_idr"], 1000)
        self.assertEqual(item["observation"]["source_kind"], "manual_fallback")
        self.assertEqual(item["observation"]["evidence_note"], "Foto papan harga kios #12")

        # Missing evidence_note & invalid currency -> 422
        status_bad, res_bad = self._request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/price-benchmarks/compare",
            body={
                "offering_id": self.off_kg,
                "source_kind": "manual_fallback",
                "source_label": "Survei",
                "evidence_note": "",
                "observed_at": "not-a-date",
                "location_market": "Pasar Baru",
                "unit": "kg",
                "quantity": "1",
                "currency": "USD",
                "observed_price_idr": -10,
            },
            token=self.token_a,
        )
        self.assertEqual(status_bad, 422)
        self.assertEqual(res_bad["code"], "validation_error")

        # Reject javascript: source_url -> 422
        status_js, res_js = self._request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/price-benchmarks/compare",
            body={
                "offering_id": self.off_kg,
                "source_kind": "manual_fallback",
                "source_label": "Survei",
                "evidence_note": "Catatan",
                "source_url": "javascript:alert(1)",
                "observed_at": "2026-11-27",
                "location_market": "Pasar Baru",
                "unit": "kg",
                "quantity": "1",
                "currency": "IDR",
                "observed_price_idr": 14000,
            },
            token=self.token_a,
        )
        self.assertEqual(status_js, 422)
        self.assertEqual(res_js["code"], "validation_error")

    def test_tenant_isolation_and_catalog_ledger_invariance(self) -> None:
        # 401 unauthenticated
        status_401, _ = self._request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/price-benchmarks/compare",
            body={"offering_id": self.off_kg, "source_kind": "synthetic_demo", "snapshot_id": "demo_beras_medium_jkt"},
        )
        self.assertEqual(status_401, 401)

        # 404 anti-enumeration for non-member even with invalid payload
        status_404_nonmember, _ = self._request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/price-benchmarks/compare",
            body={"source_kind": "invalid"},
            token=self.token_b,
        )
        self.assertEqual(status_404_nonmember, 404)

        # 404 for cross-workspace offering_id
        status_404_cross, _ = self._request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/price-benchmarks/compare",
            body={
                "offering_id": self.off_b,
                "source_kind": "synthetic_demo",
                "snapshot_id": "demo_beras_medium_jkt",
            },
            token=self.token_a,
        )
        self.assertEqual(status_404_cross, 404)

        # Verify catalog & ledger unchanged
        with db_transaction(self.db_path) as conn:
            off_row = conn.execute(
                "SELECT unit_price_idr FROM offerings WHERE offering_id = ?",
                (self.off_kg,),
            ).fetchone()
            self.assertEqual(int(off_row["unit_price_idr"]), 15000)
            sales_cnt = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            stock_cnt = conn.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0]
            cash_cnt = conn.execute("SELECT COUNT(*) FROM cash_movements").fetchone()[0]
            self.assertEqual((sales_cnt, stock_cnt, cash_cnt), (0, 0, 0))

    def test_transcribed_official_bapanas_snapshot_and_invariance(self) -> None:
        # Compare kg offering against official Bapanas March 2026 Beras Medium (13378 IDR / kg)
        status, res = self._request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/price-benchmarks/compare",
            body={
                "offering_id": self.off_kg,
                "source_kind": "transcribed_official",
                "snapshot_id": "bapanas_beras_medium_maret_2026",
            },
            token=self.token_a,
        )
        self.assertEqual(status, 200)
        item = res["item"]
        self.assertEqual(item["normalized_benchmark_price_idr"], 13378)
        self.assertEqual(item["price_delta_idr"], 1622)
        obs = item["observation"]
        self.assertEqual(obs["source_kind"], "transcribed_official")
        self.assertFalse(obs["is_synthetic"])
        self.assertTrue(obs["is_historical"])
        self.assertEqual(obs["observed_at"], "2026-03")
        self.assertEqual(obs["location_market"], "Nasional (Tingkat Konsumen)")
        self.assertEqual(obs["source_url"], "https://data.badanpangan.go.id/nfs_storage/public/publication/documents/1779588677.pdf")
        self.assertIn("halaman cetak 20", obs["evidence_note"])

        # Also compare a gram offering (500 g @ Rp 7.500 -> benchmark 6689 IDR / 500 g)
        _, off_g = self.service.create_offering(
            self.ws_a,
            actor_id="actor_a",
            payload={
                "name": "Beras 500g",
                "offering_type": "goods",
                "unit": "g",
                "unit_price_idr": 7500,
                "requires_stock_movement": True,
            },
            actor="actor_a",
        )
        status_g, res_g = self._request(
            "POST",
            f"/v1/workspaces/{self.ws_a}/price-benchmarks/compare",
            body={
                "offering_id": off_g["offering_id"],
                "source_kind": "transcribed_official",
                "snapshot_id": "bapanas_beras_medium_maret_2026",
            },
            token=self.token_a,
        )
        self.assertEqual(status_g, 200)
        self.assertEqual(res_g["item"]["normalized_benchmark_price_idr"], 13)
        # Wait: 13378 / 1000 = 13.378 -> round_idr = 13 IDR per 1 g
        self.assertEqual(res_g["item"]["offering_unit"], "g")

        with db_transaction(self.db_path) as conn:
            sales_cnt = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            self.assertEqual(sales_cnt, 0)


if __name__ == "__main__":
    unittest.main()
