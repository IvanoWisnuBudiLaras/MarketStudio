"""Comprehensive automated tests for MarketStudio Issue #5 + #12/#10/#32/#11/#36/#38/#39/#20."""

from __future__ import annotations

import http.client
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

from app.db import init_db  # noqa: E402
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
            self.assertIn("getScopedKey", html)

    def test_fa_baseline_extended_and_fb_residual_invariant(self) -> None:
        _, ws_res = self._request("POST", "/v1/workspaces", {"name": "WA Pool"}, token=self.token_a)
        ws_id = ws_res["item"]["workspace_id"]
        _, off_a = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Daging", "offering_type": "goods", "unit_price_idr": 16000, "unit": "kg"},
            token=self.token_a,
        )
        off_a_id = off_a["item"]["offering_id"]
        self.assertNotIn("tax_amount", off_a["item"])
        self.assertEqual(off_a["item"]["tax_status"], "not_assessed")

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

        # F-A first sale: 0.5 kg -> HPP 5500, profit 2500, ending 2.5 kg / 27500, cash -25000
        _, s1 = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": off_a_id, "qty": "0.5", "total_price_idr": 8000}], "occurred_at": "2026-11-27T10:00:00+07:00"},
            headers={"Idempotency-Key": "fa-s1"},
            token=self.token_a,
        )
        self.assertEqual(s1["item"]["total_cogs_idr"], 5500)
        self.assertEqual(s1["item"]["gross_profit_idr"], 2500)
        _, rep_fa = self._request("GET", f"/v1/workspaces/{ws_id}/reports/daily?date=2026-11-27", token=self.token_a)
        self.assertEqual(rep_fa["report"]["ending_inventory"]["total_qty"], "2.5")
        self.assertEqual(rep_fa["report"]["ending_inventory"]["total_value_idr"], 27500)
        self.assertEqual(rep_fa["report"]["net_cash_flow_idr"], -25000)

        # F-A extended: + 0.5 + 2.0 -> HPP 5500 / 22000, ending 0 / 0
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
        self.assertEqual([s2["item"]["total_cogs_idr"], s3["item"]["total_cogs_idr"]], [5500, 22000])

        # F-B: 3 units / 10.000 -> ROUND_HALF_UP per step gives [3333, 3334, 3333], sum 10.000, ending 0 / 0
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

    def test_service_hybrid_and_concurrency_idempotency(self) -> None:
        _, ws_res = self._request("POST", "/v1/workspaces", {"name": "Hybrid WS"}, token=self.token_a)
        ws_id = ws_res["item"]["workspace_id"]
        _, svc = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Jasa", "offering_type": "service", "unit_price_idr": 50000, "tax_status": "unknown"},
            token=self.token_a,
        )
        svc_id = svc["item"]["offering_id"]
        self.assertFalse(svc["item"]["requires_stock_movement"])
        self.assertNotIn("tax_amount", svc["item"])

        _, sale_svc = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": svc_id, "qty": "1", "total_price_idr": 50000}]},
            headers={"Idempotency-Key": "svc-1"},
            token=self.token_a,
        )
        self.assertEqual(sale_svc["item"]["cogs_status"], "open")
        self.assertIsNone(sale_svc["item"]["total_cogs_idr"])

        # Concurrent identical idempotency + last-unit race
        _, g = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Last", "offering_type": "goods", "unit_price_idr": 10000},
            token=self.token_a,
        )
        g_id = g["item"]["offering_id"]
        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": g_id, "qty": "2", "total_cost_idr": 8000},
            token=self.token_a,
        )

        same_res: list[tuple[int, str]] = []
        lock = threading.Lock()

        def same_call() -> None:
            c, b = self._request(
                "POST",
                f"/v1/workspaces/{ws_id}/sales",
                {"lines": [{"offering_id": g_id, "qty": "1", "total_price_idr": 10000}]},
                headers={"Idempotency-Key": "conc-1"},
                token=self.token_a,
            )
            with lock:
                same_res.append((c, b.get("item", {}).get("sale_id", "")))

        t1 = threading.Thread(target=same_call)
        t2 = threading.Thread(target=same_call)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        self.assertEqual([r[0] for r in same_res], [201, 201])
        self.assertEqual(same_res[0][1], same_res[1][1])

        race_codes: list[int] = []

        def race_call(i: int) -> None:
            c, _ = self._request(
                "POST",
                f"/v1/workspaces/{ws_id}/sales",
                {"lines": [{"offering_id": g_id, "qty": "1", "total_price_idr": 10000}]},
                headers={"Idempotency-Key": f"race-{i}"},
                token=self.token_a,
            )
            with lock:
                race_codes.append(c)

        t3 = threading.Thread(target=race_call, args=(1,))
        t4 = threading.Thread(target=race_call, args=(2,))
        t3.start()
        t4.start()
        t3.join()
        t4.join()
        self.assertEqual(sorted(race_codes), [201, 409])

    def test_p0_route_isolation_and_revoked_workspace_replay(self) -> None:
        s_bad, _ = self._request("POST", "/v1/sessions", {"actor_id": "actor_a", "passcode": "wrong"})
        self.assertEqual(s_bad, 401)

        _, ws_a = self._request(
            "POST", "/v1/workspaces", {"name": "WS A"}, headers={"Idempotency-Key": "ws-k1"}, token=self.token_a
        )
        ws_a_id = ws_a["item"]["workspace_id"]
        _, ws_b = self._request(
            "POST", "/v1/workspaces", {"name": "WS B"}, headers={"Idempotency-Key": "ws-k1"}, token=self.token_b
        )
        self.assertNotEqual(ws_a_id, ws_b["item"]["workspace_id"])

        # Anti-enumeration: non-member vs unknown -> identical 404
        s_nm, e_nm = self._request("GET", f"/v1/workspaces/{ws_a_id}/offerings", token=self.token_b)
        s_uk, e_uk = self._request("GET", "/v1/workspaces/ws_missing/offerings", token=self.token_b)
        self.assertEqual((s_nm, s_uk), (404, 404))
        self.assertEqual(e_nm["code"], e_uk["code"])

        # Revoke membership -> POST /v1/workspaces replay with same key is rejected (403)
        BaselineService(db_path=self.db_path).revoke_membership(ws_a_id, "actor_a")
        s_rep, _ = self._request(
            "POST", "/v1/workspaces", {"name": "WS A"}, headers={"Idempotency-Key": "ws-k1"}, token=self.token_a
        )
        self.assertEqual(s_rep, 403)

    def test_chronology_audit_cutoff_and_strict_validation(self) -> None:
        # Invalid timezone -> 422
        s_tz, _ = self._request("POST", "/v1/workspaces", {"name": "TZ", "timezone": "Mars/Olympus"}, token=self.token_a)
        self.assertEqual(s_tz, 422)

        _, ws_res = self._request("POST", "/v1/workspaces", {"name": "Chrono WS"}, token=self.token_a)
        ws_id = ws_res["item"]["workspace_id"]
        _, off = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Barang", "offering_type": "goods", "unit_price_idr": 6000},
            token=self.token_a,
        )
        off_id = off["item"]["offering_id"]

        # Contradictory requires_stock_movement -> 422
        s_contra, _ = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Jasa Bad", "offering_type": "service", "unit_price_idr": 1000, "requires_stock_movement": True},
            token=self.token_a,
        )
        self.assertEqual(s_contra, 422)

        # Purchase D, Sale D+1 -> Backdated Purchase D rejected (422 out_of_order_timestamp)
        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_id, "qty": "3", "total_cost_idr": 12000, "occurred_at": "2026-11-26T10:00:00+07:00"},
            token=self.token_a,
        )
        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": off_id, "qty": "1", "total_price_idr": 6000}], "occurred_at": "2026-11-27T10:00:00+07:00"},
            token=self.token_a,
        )
        s_back_pur, err_bp = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_id, "qty": "1", "total_cost_idr": 4000, "occurred_at": "2026-11-26T12:00:00+07:00"},
            token=self.token_a,
        )
        self.assertEqual(s_back_pur, 422)
        self.assertEqual(err_bp["code"], "out_of_order_timestamp")

        # Audit drill-down cutoff: D report must not include D+1 audit events
        _, rep_d = self._request("GET", f"/v1/workspaces/{ws_id}/reports/daily?date=2026-11-26", token=self.token_a)
        self.assertEqual(len(rep_d["report"]["drill_down"]["audit_events"]), 0)

        # Falsy/naive occurred_at, extreme qty, bad Content-Length/non-UTF-8
        s_empty_ts, _ = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_id, "qty": "1", "total_cost_idr": 1000, "occurred_at": ""},
            token=self.token_a,
        )
        s_naive_ts, _ = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_id, "qty": "1", "total_cost_idr": 1000, "occurred_at": "2026-11-27T10:00:00"},
            token=self.token_a,
        )
        s_huge_qty, _ = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_id, "qty": "1e30", "total_cost_idr": 1000},
            token=self.token_a,
        )
        self.assertEqual((s_empty_ts, s_naive_ts, s_huge_qty), (422, 422, 422))

        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("POST", "/v1/sessions", body=b"\xff\xfe", headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 422)

    def test_fault_injection_and_db_backfill(self) -> None:
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
            raise RuntimeError("Crash")

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

        # Simulate pre-inventory_pools DB and verify init_db() backfills accurately
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("DELETE FROM inventory_pools WHERE workspace_id = ?", (ws_id,))
            conn.commit()
        init_db(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn:
            pool = conn.execute(
                "SELECT qty_on_hand, total_value_idr FROM inventory_pools WHERE workspace_id = ? AND offering_id = ?",
                (ws_id, off_id),
            ).fetchone()
            self.assertEqual((float(pool[0]), pool[1]), (2.0, 4000))


if __name__ == "__main__":
    unittest.main()
