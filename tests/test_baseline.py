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
        self.token_a = self._login("actor_a", "dev-a-pass")
        self.token_b = self._login("actor_b", "dev-b-pass")

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

    def test_browser_entrypoint_xss_safe_and_counters(self) -> None:
        with urllib.request.urlopen(f"{self.base_url}/") as resp:
            self.assertEqual(resp.status, 200)
            html = resp.read().decode("utf-8")
            self.assertIn("MarketStudio", html)
            self.assertNotIn(".innerHTML", html)
            self.assertIn("catalogReqSeq", html)
            self.assertIn("reportReqSeq", html)

    def test_session_credential_binding_and_anti_enumeration(self) -> None:
        # Wrong passcode -> 401
        s_bad, _ = self._request("POST", "/v1/sessions", {"actor_id": "actor_a", "passcode": "wrong"})
        self.assertEqual(s_bad, 401)

        # create-workspace idempotency key scoped to principal
        _, ws_a = self._request(
            "POST", "/v1/workspaces", {"name": "WS A"}, headers={"Idempotency-Key": "ws-k1"}, token=self.token_a
        )
        _, ws_b = self._request(
            "POST", "/v1/workspaces", {"name": "WS B"}, headers={"Idempotency-Key": "ws-k1"}, token=self.token_b
        )
        self.assertNotEqual(ws_a["item"]["workspace_id"], ws_b["item"]["workspace_id"])

        # Anti-enumeration: non-member vs unknown workspace return identical 404 shape
        s_nonmember, e_nonmember = self._request(
            "GET", f"/v1/workspaces/{ws_a['item']['workspace_id']}/offerings", token=self.token_b
        )
        s_unknown, e_unknown = self._request(
            "GET", "/v1/workspaces/ws_does_not_exist/offerings", token=self.token_b
        )
        self.assertEqual((s_nonmember, s_unknown), (404, 404))
        self.assertEqual(e_nonmember["code"], e_unknown["code"])
        self.assertEqual(e_nonmember["message"], e_unknown["message"])

    def test_fa_extended_and_fb_wa_pool_residual_invariant(self) -> None:
        _, ws_res = self._request("POST", "/v1/workspaces", {"name": "WA Pool"}, token=self.token_a)
        ws_id = ws_res["item"]["workspace_id"]
        _, off_a = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Daging", "offering_type": "goods", "unit_price_idr": 16000, "unit": "kg"},
            token=self.token_a,
        )
        off_a_id = off_a["item"]["offering_id"]

        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_a_id, "qty": "2", "total_cost_idr": 20000, "occurred_at": "2026-11-27T08:00:00+07:00"},
            token=self.token_a,
        )
        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_a_id, "qty": "1", "total_cost_idr": 13000, "occurred_at": "2026-11-27T09:00:00+07:00"},
            token=self.token_a,
        )

        # F-A extended: 0.5 + 0.5 + 2.0 -> HPP 5.500 / 5.500 / 22.000, ending 0 / 0
        _, s1 = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": off_a_id, "qty": "0.5", "total_price_idr": 8000}], "occurred_at": "2026-11-27T10:00:00+07:00"},
            token=self.token_a,
        )
        _, s2 = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": off_a_id, "qty": "0.5", "total_price_idr": 8000}], "occurred_at": "2026-11-27T11:00:00+07:00"},
            token=self.token_a,
        )
        _, s3 = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": off_a_id, "qty": "2.0", "total_price_idr": 32000}], "occurred_at": "2026-11-27T12:00:00+07:00"},
            token=self.token_a,
        )
        self.assertEqual(
            [s1["item"]["total_cogs_idr"], s2["item"]["total_cogs_idr"], s3["item"]["total_cogs_idr"]],
            [5500, 5500, 22000],
        )

        # F-B: 3 units / 10.000 -> 1 + 1 + 1 = 3.333 / 3.333 / 3.334, ending 0 / 0
        _, off_b = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Unit B", "offering_type": "goods", "unit_price_idr": 5000},
            token=self.token_a,
        )
        off_b_id = off_b["item"]["offering_id"]
        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_b_id, "qty": "3", "total_cost_idr": 10000, "occurred_at": "2026-11-27T13:00:00+07:00"},
            token=self.token_a,
        )
        cogs_b = []
        for idx in range(3):
            _, sb = self._request(
                "POST",
                f"/v1/workspaces/{ws_id}/sales",
                {"lines": [{"offering_id": off_b_id, "qty": "1", "total_price_idr": 5000}], "occurred_at": f"2026-11-27T14:0{idx}:00+07:00"},
                token=self.token_a,
            )
            cogs_b.append(sb["item"]["total_cogs_idr"])
        self.assertEqual(cogs_b, [3333, 3334, 3333])
        self.assertEqual(sum(cogs_b), 10000)

        _, rep = self._request("GET", f"/v1/workspaces/{ws_id}/reports/daily?date=2026-11-27", token=self.token_a)
        self.assertEqual(rep["report"]["ending_inventory"]["total_value_idr"], 0)

    def test_historical_cutoff_chronology_and_validation(self) -> None:
        _, ws_res = self._request("POST", "/v1/workspaces", {"name": "History WS"}, token=self.token_a)
        ws_id = ws_res["item"]["workspace_id"]
        _, off = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Barang", "offering_type": "goods", "unit_price_idr": 6000},
            token=self.token_a,
        )
        off_id = off["item"]["offering_id"]

        # Purchase on D (2026-11-26)
        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_id, "qty": "3", "total_cost_idr": 12000, "occurred_at": "2026-11-26T10:00:00+07:00"},
            token=self.token_a,
        )
        # Sale on D+1 (2026-11-27)
        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": off_id, "qty": "1", "total_price_idr": 6000}], "occurred_at": "2026-11-27T10:00:00+07:00"},
            token=self.token_a,
        )

        # Report D shows 3 units / 12000; Report D+1 shows 2 units / 8000
        _, rep_d = self._request("GET", f"/v1/workspaces/{ws_id}/reports/daily?date=2026-11-26", token=self.token_a)
        _, rep_d1 = self._request("GET", f"/v1/workspaces/{ws_id}/reports/daily?date=2026-11-27", token=self.token_a)
        self.assertEqual(rep_d["report"]["ending_inventory"]["total_qty"], "3")
        self.assertEqual(rep_d["report"]["ending_inventory"]["total_value_idr"], 12000)
        self.assertEqual(rep_d1["report"]["ending_inventory"]["total_qty"], "2")
        self.assertEqual(rep_d1["report"]["ending_inventory"]["total_value_idr"], 8000)

        # Backdated sale on D after D+1 movement -> 422 out_of_order_timestamp
        s_back, err_back = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": off_id, "qty": "1"}], "occurred_at": "2026-11-26T12:00:00+07:00"},
            token=self.token_a,
        )
        self.assertEqual(s_back, 422)
        self.assertEqual(err_back["code"], "out_of_order_timestamp")

        # Non-cash, bad date, NaN -> 422
        s_def, _ = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_id, "qty": "1", "total_cost_idr": 1000, "payment_method": "deferred"},
            token=self.token_a,
        )
        s_bad_ts, _ = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_id, "qty": "1", "total_cost_idr": 1000, "occurred_at": "not-a-date"},
            token=self.token_a,
        )
        s_nan, _ = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_id, "qty": "NaN", "total_cost_idr": 1000},
            token=self.token_a,
        )
        self.assertEqual((s_def, s_bad_ts, s_nan), (422, 422, 422))

    def test_fault_injection_stages_rollback(self) -> None:
        _, ws_res = self._request("POST", "/v1/workspaces", {"name": "Fault WS"}, token=self.token_a)
        ws_id = ws_res["item"]["workspace_id"]
        _, off = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Item", "offering_type": "goods", "unit_price_idr": 5000},
            token=self.token_a,
        )
        off_id = off["item"]["offering_id"]
        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_id, "qty": "2", "total_cost_idr": 4000},
            token=self.token_a,
        )

        svc = BaselineService(db_path=self.db_path)

        def boom(_conn: sqlite3.Connection) -> None:
            raise RuntimeError("Simulated crash")

        for stage in ("stock_movements", "pre_commit"):
            with self.assertRaises(RuntimeError):
                svc.create_sale(
                    ws_id,
                    "actor_a",
                    {"lines": [{"offering_id": off_id, "qty": "1", "total_price_idr": 5000}]},
                    idempotency_key=f"fault-{stage}",
                    actor="actor_a",
                    fault_injector=boom,
                    fault_stage=stage,
                )

        with closing(sqlite3.connect(self.db_path)) as conn:
            sales_cnt = conn.execute("SELECT COUNT(*) FROM sales WHERE workspace_id = ?", (ws_id,)).fetchone()[0]
            idem_cnt = conn.execute("SELECT COUNT(*) FROM idempotency_keys WHERE workspace_id = ?", (ws_id,)).fetchone()[0]
        self.assertEqual((sales_cnt, idem_cnt), (0, 0))


if __name__ == "__main__":
    unittest.main()
