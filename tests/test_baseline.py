"""Automated tests for MarketStudio Issue #5 runnable baseline."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ["MARKETSTUDIO_QUIET_LOGS"] = "1"

from app.server import create_server  # noqa: E402


class BaselineIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "test_baseline.db")
        self._start_server()

    def tearDown(self) -> None:
        self._stop_server()
        self.tmpdir.cleanup()

    def _start_server(self) -> None:
        self.server = create_server(host="127.0.0.1", port=0, db_path=self.db_path)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def _stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict]:
        req_headers = dict(headers or {})
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
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_browser_entrypoint_and_health(self) -> None:
        with urllib.request.urlopen(f"{self.base_url}/") as resp:
            self.assertEqual(resp.status, 200)
            html = resp.read().decode("utf-8")
            self.assertIn("MarketStudio", html)

        status, health = self._request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["status"], "ok")

    def test_positive_flow_goods_service_hybrid_and_persistence(self) -> None:
        # 1. Create workspace
        status, ws_res = self._request(
            "POST",
            "/v1/workspaces",
            {"name": "Bakso Sintetis", "business_type": "umkm_hybrid"},
            headers={"Idempotency-Key": "ws-create-1"},
        )
        self.assertEqual(status, 201)
        ws_id = ws_res["item"]["workspace_id"]

        # 2. Create goods offering (WA valuation, no default tax=0)
        status, goods_res = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {
                "name": "Bakso Urat",
                "offering_type": "goods",
                "unit_price_idr": 18000,
                "unit": "porsi",
            },
            headers={"X-Workspace-Id": ws_id, "Idempotency-Key": "off-1"},
        )
        self.assertEqual(status, 201)
        goods = goods_res["item"]
        self.assertTrue(goods["requires_stock_movement"])
        self.assertEqual(goods["valuation_method"], "WA")
        self.assertEqual(goods["tax_status"], "not_assessed")
        self.assertIsNone(goods["tax_amount"])

        # 3. Create service offering (no stock movement required)
        status, svc_res = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {
                "name": "Jasa Katering",
                "offering_type": "service",
                "unit_price_idr": 250000,
                "unit": "paket",
            },
            headers={"X-Workspace-Id": ws_id},
        )
        self.assertEqual(status, 201)
        self.assertFalse(svc_res["item"]["requires_stock_movement"])
        self.assertIsNone(svc_res["item"]["valuation_method"])
        self.assertIsNone(svc_res["item"]["tax_amount"])

        # 4. Create hybrid offering
        status, hyb_res = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {
                "name": "Paket Hampers + Kirim",
                "offering_type": "hybrid",
                "unit_price_idr": 120000,
                "unit": "paket",
            },
            headers={"X-Workspace-Id": ws_id},
        )
        self.assertEqual(status, 201)
        self.assertEqual(hyb_res["item"]["offering_type"], "hybrid")

        # 5. Restart server and verify persistence
        self._stop_server()
        self._start_server()

        status, list_res = self._request(
            "GET",
            f"/v1/workspaces/{ws_id}/offerings",
            headers={"X-Workspace-Id": ws_id},
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(list_res["items"]), 3)
        self.assertTrue(all(i["workspace_id"] == ws_id for i in list_res["items"]))

    def test_validation_and_idempotency(self) -> None:
        _, ws_res = self._request("POST", "/v1/workspaces", {"name": "Toko Valid"})
        ws_id = ws_res["item"]["workspace_id"]

        # Reject empty/invalid name
        status, err = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "   ", "offering_type": "goods", "unit_price_idr": 1000},
            headers={"X-Workspace-Id": ws_id},
        )
        self.assertEqual(status, 422)
        self.assertEqual(err["code"], "validation_error")
        self.assertIn("name", err["field_errors"])

        # Idempotency replay vs conflict
        payload = {"name": "Kopi Susu", "offering_type": "goods", "unit_price_idr": 15000}
        s1, r1 = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            payload,
            headers={"X-Workspace-Id": ws_id, "Idempotency-Key": "idem-abc"},
        )
        s2, r2 = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            payload,
            headers={"X-Workspace-Id": ws_id, "Idempotency-Key": "idem-abc"},
        )
        self.assertEqual(s1, 201)
        self.assertEqual(s2, 201)
        self.assertEqual(r1["item"]["offering_id"], r2["item"]["offering_id"])

        s3, err_conflict = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Kopi Hitam", "offering_type": "goods", "unit_price_idr": 12000},
            headers={"X-Workspace-Id": ws_id, "Idempotency-Key": "idem-abc"},
        )
        self.assertEqual(s3, 409)
        self.assertEqual(err_conflict["code"], "idempotency_conflict")

    def test_cross_workspace_tenant_isolation(self) -> None:
        _, ws_a = self._request("POST", "/v1/workspaces", {"name": "Tenant A"})
        _, ws_b = self._request("POST", "/v1/workspaces", {"name": "Tenant B"})
        ws_a_id = ws_a["item"]["workspace_id"]
        ws_b_id = ws_b["item"]["workspace_id"]

        _, off_a = self._request(
            "POST",
            f"/v1/workspaces/{ws_a_id}/offerings",
            {"name": "Produk Rahasia A", "offering_type": "goods", "unit_price_idr": 50000},
            headers={"X-Workspace-Id": ws_a_id},
        )
        off_a_id = off_a["item"]["offering_id"]

        # Mismatched X-Workspace-Id header -> 403
        status, err = self._request(
            "GET",
            f"/v1/workspaces/{ws_a_id}/offerings",
            headers={"X-Workspace-Id": ws_b_id},
        )
        self.assertEqual(status, 403)
        self.assertEqual(err["code"], "forbidden_workspace")

        # Missing X-Workspace-Id header -> 403
        status, _ = self._request("GET", f"/v1/workspaces/{ws_a_id}/offerings")
        self.assertEqual(status, 403)

        # Accessing Tenant A's offering under Tenant B's URL -> 404 (no tenant leakage)
        status, err_not_found = self._request(
            "GET",
            f"/v1/workspaces/{ws_b_id}/offerings/{off_a_id}",
            headers={"X-Workspace-Id": ws_b_id},
        )
        self.assertEqual(status, 404)
        self.assertEqual(err_not_found["code"], "offering_not_found")


if __name__ == "__main__":
    unittest.main()
