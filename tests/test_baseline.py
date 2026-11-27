"""Automated tests for MarketStudio Issue #5 + #12/#10/#32/#11/#36/#38/#39/#20."""

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

from app.server import create_server  # noqa: E402
from app.service import BaselineService  # noqa: E402


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
            body_bytes = exc.read()
            exc.close()
            return exc.code, json.loads(body_bytes.decode("utf-8"))

    def test_browser_entrypoint_and_health(self) -> None:
        with urllib.request.urlopen(f"{self.base_url}/") as resp:
            self.assertEqual(resp.status, 200)
            html = resp.read().decode("utf-8")
            self.assertIn("MarketStudio", html)

        status, health = self._request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["status"], "ok")

    def test_fixture_fa_wa_valuation_report_and_idempotency(self) -> None:
        """Fixture F-A: 27 Nov 2026 Asia/Jakarta, buy 2kg@20k + 1kg@13k, sell 0.5kg@8k."""
        _, ws_res = self._request("POST", "/v1/workspaces", {"name": "Workspace A"})
        ws_id = ws_res["item"]["workspace_id"]

        _, off_res = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Daging Sapi", "offering_type": "goods", "unit_price_idr": 16000, "unit": "kg"},
            headers={"X-Workspace-Id": ws_id},
        )
        off_id = off_res["item"]["offering_id"]

        # Two cash purchases on 2026-11-27 Asia/Jakarta
        s1, _ = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {
                "offering_id": off_id,
                "qty": "2",
                "total_cost_idr": 20000,
                "occurred_at": "2026-11-27T08:00:00+07:00",
            },
            headers={"X-Workspace-Id": ws_id, "Idempotency-Key": "fa-pur-1"},
        )
        s2, _ = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {
                "offering_id": off_id,
                "qty": "1",
                "total_cost_idr": 13000,
                "occurred_at": "2026-11-27T09:00:00+07:00",
            },
            headers={"X-Workspace-Id": ws_id, "Idempotency-Key": "fa-pur-2"},
        )
        self.assertEqual((s1, s2), (201, 201))

        # Cash sale 0.5 kg @ Rp8.000 + idempotency replay + 409 mismatch
        sale_payload = {
            "lines": [{"offering_id": off_id, "qty": "0.5", "total_price_idr": 8000}],
            "occurred_at": "2026-11-27T10:00:00+07:00",
        }
        s3, sale_res = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            sale_payload,
            headers={"X-Workspace-Id": ws_id, "Idempotency-Key": "fa-sale-1"},
        )
        s4, replay_res = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            sale_payload,
            headers={"X-Workspace-Id": ws_id, "Idempotency-Key": "fa-sale-1"},
        )
        self.assertEqual(s3, 201)
        self.assertEqual(s4, 201)
        self.assertEqual(sale_res["item"]["sale_id"], replay_res["item"]["sale_id"])
        self.assertEqual(sale_res["item"]["total_cogs_idr"], 5500)
        self.assertEqual(sale_res["item"]["gross_profit_idr"], 2500)

        s5, conflict_res = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": off_id, "qty": "1", "total_price_idr": 16000}]},
            headers={"X-Workspace-Id": ws_id, "Idempotency-Key": "fa-sale-1"},
        )
        self.assertEqual(s5, 409)
        self.assertEqual(conflict_res["code"], "idempotency_conflict")

        # Daily report verification
        sr, rep_res = self._request(
            "GET",
            f"/v1/workspaces/{ws_id}/reports/daily?date=2026-11-27",
            headers={"X-Workspace-Id": ws_id},
        )
        self.assertEqual(sr, 200)
        rep = rep_res["report"]
        self.assertEqual(rep["revenue_idr"], 8000)
        self.assertEqual(rep["cogs_idr"], 5500)
        self.assertEqual(rep["gross_profit_idr"], 2500)
        self.assertEqual(rep["net_cash_flow_idr"], -25000)
        self.assertEqual(rep["ending_inventory"]["total_qty"], "2.5")
        self.assertEqual(rep["ending_inventory"]["total_value_idr"], 27500)
        self.assertEqual(rep["tax_status"], "not_assessed")
        self.assertEqual(len(rep["drill_down"]["sales"]), 1)
        self.assertEqual(len(rep["drill_down"]["purchases"]), 2)

    def test_service_and_hybrid_open_cost_flow(self) -> None:
        _, ws_res = self._request("POST", "/v1/workspaces", {"name": "Studio Jasa"})
        ws_id = ws_res["item"]["workspace_id"]

        _, svc_res = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Jasa Desain", "offering_type": "service", "unit_price_idr": 100000, "unit": "paket"},
            headers={"X-Workspace-Id": ws_id},
        )
        svc_id = svc_res["item"]["offering_id"]

        # Service purchase rejected (no stock movement)
        sp, err = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": svc_id, "qty": "1", "total_cost_idr": 10000},
            headers={"X-Workspace-Id": ws_id},
        )
        self.assertEqual(sp, 422)
        self.assertEqual(err["code"], "service_no_stock")

        # Service sale succeeds with cogs_status=open and total_cogs_idr=None
        ss, sale_res = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": svc_id, "qty": "1", "total_price_idr": 100000}]},
            headers={"X-Workspace-Id": ws_id},
        )
        self.assertEqual(ss, 201)
        self.assertEqual(sale_res["item"]["cogs_status"], "open")
        self.assertIsNone(sale_res["item"]["total_cogs_idr"])

        _, rep_res = self._request(
            "GET",
            f"/v1/workspaces/{ws_id}/reports/daily",
            headers={"X-Workspace-Id": ws_id},
        )
        self.assertEqual(rep_res["report"]["cogs_status"], "open")
        self.assertEqual(rep_res["report"]["gross_profit_status"], "unavailable")
        self.assertIsNone(rep_res["report"]["gross_profit_idr"])

    def test_concurrency_last_unit_race_and_fault_rollback(self) -> None:
        """F-B style competing sales on last unit -> 1 winner, 0 negative stock, plus fault rollback."""
        _, ws_res = self._request("POST", "/v1/workspaces", {"name": "Workspace B"})
        ws_id = ws_res["item"]["workspace_id"]
        _, off_res = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Item Terakhir", "offering_type": "goods", "unit_price_idr": 10000},
            headers={"X-Workspace-Id": ws_id},
        )
        off_id = off_res["item"]["offering_id"]

        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_id, "qty": "1", "total_cost_idr": 5000},
            headers={"X-Workspace-Id": ws_id},
        )

        results: list[int] = []
        lock = threading.Lock()

        def attempt_sale(idx: int) -> None:
            code, _ = self._request(
                "POST",
                f"/v1/workspaces/{ws_id}/sales",
                {"lines": [{"offering_id": off_id, "qty": "1", "total_price_idr": 10000}]},
                headers={"X-Workspace-Id": ws_id, "Idempotency-Key": f"race-{idx}"},
            )
            with lock:
                results.append(code)

        t1 = threading.Thread(target=attempt_sale, args=(1,))
        t2 = threading.Thread(target=attempt_sale, args=(2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(sorted(results), [201, 409])

        # Fault injection test: mid-transaction failure leaves zero partial rows
        svc = BaselineService(db_path=self.db_path)
        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_id, "qty": "1", "total_cost_idr": 5000},
            headers={"X-Workspace-Id": ws_id},
        )

        def boom(_conn: sqlite3.Connection) -> None:
            raise RuntimeError("Simulated mid-commit crash")

        with self.assertRaises(RuntimeError):
            svc.create_sale(
                ws_id,
                ws_id,
                {"lines": [{"offering_id": off_id, "qty": "1", "total_price_idr": 10000}]},
                idempotency_key="fault-1",
                fault_injector=boom,
            )

        with closing(sqlite3.connect(self.db_path)) as conn:
            sales_count = conn.execute(
                "SELECT COUNT(*) FROM sales WHERE workspace_id = ?", (ws_id,)
            ).fetchone()[0]
            idem_count = conn.execute(
                "SELECT COUNT(*) FROM idempotency_keys WHERE idempotency_key = 'fault-1'"
            ).fetchone()[0]
        self.assertEqual(sales_count, 1)  # Only the race winner
        self.assertEqual(idem_count, 0)

    def test_p0_route_isolation_matrix(self) -> None:
        """All exposed P0 routes reject cross-workspace and revoked actors."""
        _, ws_a = self._request("POST", "/v1/workspaces", {"name": "Tenant A"})
        _, ws_b = self._request("POST", "/v1/workspaces", {"name": "Tenant B"})
        ws_a_id = ws_a["item"]["workspace_id"]
        ws_b_id = ws_b["item"]["workspace_id"]

        _, off_a = self._request(
            "POST",
            f"/v1/workspaces/{ws_a_id}/offerings",
            {"name": "Produk A", "offering_type": "goods", "unit_price_idr": 10000},
            headers={"X-Workspace-Id": ws_a_id},
        )
        off_a_id = off_a["item"]["offering_id"]

        routes = [
            ("GET", f"/v1/workspaces/{ws_a_id}/offerings", None),
            ("GET", f"/v1/workspaces/{ws_a_id}/offerings/{off_a_id}", None),
            ("POST", f"/v1/workspaces/{ws_a_id}/offerings", {"name": "X", "offering_type": "goods", "unit_price_idr": 1}),
            ("POST", f"/v1/workspaces/{ws_a_id}/purchases", {"offering_id": off_a_id, "qty": "1", "total_cost_idr": 100}),
            ("POST", f"/v1/workspaces/{ws_a_id}/sales", {"lines": [{"offering_id": off_a_id, "qty": "1"}]}),
            ("GET", f"/v1/workspaces/{ws_a_id}/reports/daily", None),
        ]
        for method, path, body in routes:
            # Cross-workspace header -> 403
            c1, _ = self._request(method, path, body, headers={"X-Workspace-Id": ws_b_id})
            self.assertEqual(c1, 403, f"Expected 403 for cross-workspace {method} {path}")
            # Revoked actor -> 403
            c2, _ = self._request(
                method, path, body, headers={"X-Workspace-Id": ws_a_id, "X-Actor-Status": "revoked"}
            )
            self.assertEqual(c2, 403, f"Expected 403 for revoked actor {method} {path}")


if __name__ == "__main__":
    unittest.main()
