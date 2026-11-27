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

from app.server import WEB_INDEX_PATH, create_server  # noqa: E402
from app.service import BaselineService  # noqa: E402


class BaselineIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "test_baseline.db")
        self._start_server()
        self.token_a = self._login("actor_a")
        self.token_b = self._login("actor_b")

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

    def _login(self, actor_id: str) -> str:
        status, res = self._request("POST", "/v1/sessions", {"actor_id": actor_id})
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

    def test_browser_entrypoint_xss_safe_and_health(self) -> None:
        with urllib.request.urlopen(f"{self.base_url}/") as resp:
            self.assertEqual(resp.status, 200)
            html = resp.read().decode("utf-8")
            self.assertIn("MarketStudio", html)
            self.assertNotIn(".innerHTML", html)

        status, health = self._request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["status"], "ok")

    def test_fixture_fa_wa_valuation_report_and_idempotency(self) -> None:
        """Fixture F-A: 27 Nov 2026 Asia/Jakarta, buy 2kg@20k + 1kg@13k, sell 0.5kg@8k."""
        _, ws_res = self._request("POST", "/v1/workspaces", {"name": "Workspace A"}, token=self.token_a)
        ws_id = ws_res["item"]["workspace_id"]

        _, off_res = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Daging Sapi", "offering_type": "goods", "unit_price_idr": 16000, "unit": "kg"},
            token=self.token_a,
        )
        off_id = off_res["item"]["offering_id"]
        self.assertNotIn("tax_amount", off_res["item"])

        s1, _ = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {
                "offering_id": off_id,
                "qty": "2",
                "total_cost_idr": 20000,
                "occurred_at": "2026-11-27T08:00:00+07:00",
            },
            headers={"Idempotency-Key": "fa-pur-1"},
            token=self.token_a,
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
            headers={"Idempotency-Key": "fa-pur-2"},
            token=self.token_a,
        )
        self.assertEqual((s1, s2), (201, 201))

        sale_payload = {
            "lines": [{"offering_id": off_id, "qty": "0.5", "total_price_idr": 8000}],
            "occurred_at": "2026-11-27T10:00:00+07:00",
        }
        s3, sale_res = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            sale_payload,
            headers={"Idempotency-Key": "fa-sale-1"},
            token=self.token_a,
        )
        s4, replay_res = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            sale_payload,
            headers={"Idempotency-Key": "fa-sale-1"},
            token=self.token_a,
        )
        self.assertEqual((s3, s4), (201, 201))
        self.assertEqual(sale_res["item"]["sale_id"], replay_res["item"]["sale_id"])
        self.assertEqual(sale_res["item"]["total_cogs_idr"], 5500)
        self.assertEqual(sale_res["item"]["gross_profit_idr"], 2500)

        s5, conflict_res = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": off_id, "qty": "1", "total_price_idr": 16000}]},
            headers={"Idempotency-Key": "fa-sale-1"},
            token=self.token_a,
        )
        self.assertEqual(s5, 409)
        self.assertEqual(conflict_res["code"], "idempotency_conflict")

        sr, rep_res = self._request(
            "GET",
            f"/v1/workspaces/{ws_id}/reports/daily?date=2026-11-27",
            token=self.token_a,
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

    def test_strict_validation_boolean_and_locked_wa(self) -> None:
        _, ws_res = self._request("POST", "/v1/workspaces", {"name": "Toko Ketat"}, token=self.token_a)
        ws_id = ws_res["item"]["workspace_id"]

        s_bool, err_bool = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {
                "name": "Barang A",
                "offering_type": "goods",
                "unit_price_idr": 1000,
                "requires_stock_movement": "false",
            },
            token=self.token_a,
        )
        self.assertEqual(s_bool, 422)
        self.assertIn("requires_stock_movement", err_bool["field_errors"])

        s_fifo, err_fifo = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {
                "name": "Barang B",
                "offering_type": "goods",
                "unit_price_idr": 1000,
                "valuation_method": "FIFO",
            },
            token=self.token_a,
        )
        self.assertEqual(s_fifo, 422)
        self.assertIn("valuation_method", err_fifo["field_errors"])

    def test_concurrent_identical_idempotency_and_last_unit_race(self) -> None:
        _, ws_res = self._request("POST", "/v1/workspaces", {"name": "Workspace B"}, token=self.token_a)
        ws_id = ws_res["item"]["workspace_id"]
        _, off_res = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Item Race", "offering_type": "goods", "unit_price_idr": 10000},
            token=self.token_a,
        )
        off_id = off_res["item"]["offering_id"]
        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_id, "qty": "2", "total_cost_idr": 10000},
            token=self.token_a,
        )

        # 1. Two concurrent identical POSTs with SAME Idempotency-Key -> both 201, same sale_id
        same_results: list[tuple[int, str]] = []
        lock = threading.Lock()

        def same_key_sale() -> None:
            code, body = self._request(
                "POST",
                f"/v1/workspaces/{ws_id}/sales",
                {"lines": [{"offering_id": off_id, "qty": "1", "total_price_idr": 10000}]},
                headers={"Idempotency-Key": "concurrent-same-key"},
                token=self.token_a,
            )
            with lock:
                same_results.append((code, body.get("item", {}).get("sale_id", "")))

        t1 = threading.Thread(target=same_key_sale)
        t2 = threading.Thread(target=same_key_sale)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        self.assertEqual([r[0] for r in same_results], [201, 201])
        self.assertEqual(same_results[0][1], same_results[1][1])

        # 2. Competing sales on last unit with DIFFERENT keys -> 1 winner (201), 1 loser (409)
        race_codes: list[int] = []

        def race_sale(idx: int) -> None:
            code, _ = self._request(
                "POST",
                f"/v1/workspaces/{ws_id}/sales",
                {"lines": [{"offering_id": off_id, "qty": "1", "total_price_idr": 10000}]},
                headers={"Idempotency-Key": f"race-{idx}"},
                token=self.token_a,
            )
            with lock:
                race_codes.append(code)

        t3 = threading.Thread(target=race_sale, args=(1,))
        t4 = threading.Thread(target=race_sale, args=(2,))
        t3.start()
        t4.start()
        t3.join()
        t4.join()
        self.assertEqual(sorted(race_codes), [201, 409])

    def test_p0_route_isolation_and_revoked_actor_replay(self) -> None:
        _, ws_a = self._request("POST", "/v1/workspaces", {"name": "Tenant A"}, token=self.token_a)
        _, ws_b = self._request("POST", "/v1/workspaces", {"name": "Tenant B"}, token=self.token_b)
        ws_a_id = ws_a["item"]["workspace_id"]
        ws_b_id = ws_b["item"]["workspace_id"]

        # GET /v1/workspaces filters strictly to verified actor's memberships
        _, list_a = self._request("GET", "/v1/workspaces", token=self.token_a)
        _, list_b = self._request("GET", "/v1/workspaces", token=self.token_b)
        self.assertEqual([w["workspace_id"] for w in list_a["items"]], [ws_a_id])
        self.assertEqual([w["workspace_id"] for w in list_b["items"]], [ws_b_id])

        # Unauthenticated -> 401
        s_unauth, _ = self._request("GET", "/v1/workspaces")
        self.assertEqual(s_unauth, 401)

        _, off_a = self._request(
            "POST",
            f"/v1/workspaces/{ws_a_id}/offerings",
            {"name": "Produk A", "offering_type": "goods", "unit_price_idr": 10000},
            headers={"Idempotency-Key": "off-a-1"},
            token=self.token_a,
        )
        off_a_id = off_a["item"]["offering_id"]

        # Actor B targeting Workspace A -> 403 across all P0 routes
        routes = [
            ("GET", f"/v1/workspaces/{ws_a_id}/offerings", None),
            ("GET", f"/v1/workspaces/{ws_a_id}/offerings/{off_a_id}", None),
            ("POST", f"/v1/workspaces/{ws_a_id}/offerings", {"name": "X", "offering_type": "goods", "unit_price_idr": 1}),
            ("POST", f"/v1/workspaces/{ws_a_id}/purchases", {"offering_id": off_a_id, "qty": "1", "total_cost_idr": 100}),
            ("POST", f"/v1/workspaces/{ws_a_id}/sales", {"lines": [{"offering_id": off_a_id, "qty": "1"}]}),
            ("GET", f"/v1/workspaces/{ws_a_id}/reports/daily", None),
        ]
        for method, path, body in routes:
            c1, _ = self._request(method, path, body, token=self.token_b)
            self.assertEqual(c1, 403, f"Expected 403 for Actor B on {method} {path}")

        # Actor B querying Tenant A's offering under Tenant B's own workspace -> 404 (no leakage)
        c_leak, _ = self._request("GET", f"/v1/workspaces/{ws_b_id}/offerings/{off_a_id}", token=self.token_b)
        self.assertEqual(c_leak, 404)

        # Revoke Actor A's membership -> Actor A cannot replay valid old Idempotency-Key
        BaselineService(db_path=self.db_path).revoke_membership(ws_a_id, "actor_a")
        c_revoked, _ = self._request(
            "POST",
            f"/v1/workspaces/{ws_a_id}/offerings",
            {"name": "Produk A", "offering_type": "goods", "unit_price_idr": 10000},
            headers={"Idempotency-Key": "off-a-1"},
            token=self.token_a,
        )
        self.assertEqual(c_revoked, 403)


if __name__ == "__main__":
    unittest.main()
