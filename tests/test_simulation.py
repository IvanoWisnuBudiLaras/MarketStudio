"""Automated tests for MarketStudio Issue #15: Price & Discount Simulation."""

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


class SimulationIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "test_sim.db")
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
        self.tmpdir.cleanup()

    def _request(self, method: str, path: str, token: str | None = None, body: dict | None = None) -> tuple[int, dict]:
        headers: dict[str, str] = {}
        data = None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read().decode("utf-8"))

    def _login(self, actor_id: str, passcode: str) -> str:
        status, data = self._request("POST", "/v1/sessions", body={"actor_id": actor_id, "passcode": passcode})
        self.assertEqual(status, 201)
        return data["item"]["token"]

    def _create_workspace(self, token: str, name: str) -> str:
        status, data = self._request("POST", "/v1/workspaces", token=token, body={"name": name})
        self.assertEqual(status, 201)
        return data["item"]["workspace_id"]

    def _table_counts(self) -> dict[str, int]:
        tables = (
            "offerings",
            "sales",
            "sale_lines",
            "inventory_batches",
            "inventory_pools",
            "stock_movements",
            "cash_movements",
            "audit_events",
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}

    def test_simulation_fixture_zero_net_service_open_and_invariance(self) -> None:
        ws_a = self._create_workspace(self.token_a, "Warung Simulasi")

        # 1. Required fixture: cost 3000, price 5000, discount 20% -> net 4000, delta 1000, margin 25%
        status, data = self._request(
            "POST",
            f"/v1/workspaces/{ws_a}/simulations",
            token=self.token_a,
            body={"unit_cost_idr": 3000, "selling_price_idr": 5000, "discount_percent": "20"},
        )
        self.assertEqual(status, 200)
        item = data["item"]
        self.assertEqual(item["net_price_idr"], 4000)
        self.assertEqual(item["gross_delta_idr"], 1000)
        self.assertEqual(item["margin_percent"], "25")
        self.assertEqual(item["markup_percent"], "33.33")
        self.assertEqual(item["cost_status"], "assessed")
        self.assertEqual(item["margin_status"], "assessed")
        self.assertTrue(item["read_only"])

        # 2. Net price 0 (100% discount) -> margin_status unavailable, no divide by zero
        status_zero, data_zero = self._request(
            "POST",
            f"/v1/workspaces/{ws_a}/simulations",
            token=self.token_a,
            body={"unit_cost_idr": 3000, "selling_price_idr": 5000, "discount_percent": 100},
        )
        self.assertEqual(status_zero, 200)
        self.assertEqual(data_zero["item"]["net_price_idr"], 0)
        self.assertEqual(data_zero["item"]["margin_status"], "unavailable")
        self.assertIsNone(data_zero["item"]["margin_percent"])

        # 3. Service offering with unknown cost -> cost_status open, margin_status unavailable
        s_off, d_off = self._request(
            "POST",
            f"/v1/workspaces/{ws_a}/offerings",
            token=self.token_a,
            body={"name": "Jasa Antar", "offering_type": "service", "unit_price_idr": 10000, "unit": "trip"},
        )
        self.assertEqual(s_off, 201)
        svc_id = d_off["item"]["offering_id"]

        before_counts = self._table_counts()
        s_svc, d_svc = self._request(
            "POST",
            f"/v1/workspaces/{ws_a}/simulations",
            token=self.token_a,
            body={"offering_id": svc_id, "discount_percent": 10},
        )
        self.assertEqual(s_svc, 200)
        self.assertEqual(d_svc["item"]["net_price_idr"], 9000)
        self.assertEqual(d_svc["item"]["cost_status"], "open")
        self.assertEqual(d_svc["item"]["margin_status"], "unavailable")
        self.assertIsNone(d_svc["item"]["gross_delta_idr"])
        self.assertIsNone(d_svc["item"]["margin_percent"])
        self.assertEqual(self._table_counts(), before_counts)

    def test_simulation_tenant_isolation_and_validation(self) -> None:
        ws_a = self._create_workspace(self.token_a, "Workspace A")
        ws_b = self._create_workspace(self.token_b, "Workspace B")
        s_off, d_off = self._request(
            "POST",
            f"/v1/workspaces/{ws_a}/offerings",
            token=self.token_a,
            body={"name": "Bakso", "offering_type": "goods", "unit_price_idr": 5000, "unit": "porsi"},
        )
        self.assertEqual(s_off, 201)
        off_a = d_off["item"]["offering_id"]

        # Unauthenticated -> 401
        s_unauth, _ = self._request(
            "POST",
            f"/v1/workspaces/{ws_a}/simulations",
            body={"unit_cost_idr": 1000, "selling_price_idr": 2000},
        )
        self.assertEqual(s_unauth, 401)

        # Cross-workspace access -> 404 anti-enumeration
        s_cross_ws, _ = self._request(
            "POST",
            f"/v1/workspaces/{ws_a}/simulations",
            token=self.token_b,
            body={"unit_cost_idr": 1000, "selling_price_idr": 2000},
        )
        self.assertEqual(s_cross_ws, 404)

        # Cross-workspace offering_id -> 404 anti-enumeration
        s_cross_off, _ = self._request(
            "POST",
            f"/v1/workspaces/{ws_b}/simulations",
            token=self.token_b,
            body={"offering_id": off_a},
        )
        self.assertEqual(s_cross_off, 404)

        # Strict 422 validation
        for bad_payload in (
            {"unit_cost_idr": True, "selling_price_idr": 5000},
            {"unit_cost_idr": 1000, "selling_price_idr": -1},
            {"unit_cost_idr": 1000, "selling_price_idr": 5000, "discount_percent": 101},
            {"unit_cost_idr": 1000, "selling_price_idr": 5000, "discount_percent": "NaN"},
            {},
        ):
            s_bad, d_bad = self._request(
                "POST",
                f"/v1/workspaces/{ws_a}/simulations",
                token=self.token_a,
                body=bad_payload,
            )
            self.assertEqual(s_bad, 422)
            self.assertEqual(d_bad["code"], "validation_error")

    def test_derived_value_overflow_guard_in_sale_and_simulation(self) -> None:
        ws_a = self._create_workspace(self.token_a, "Overflow WS")
        s_off, d_off = self._request(
            "POST",
            f"/v1/workspaces/{ws_a}/offerings",
            token=self.token_a,
            body={"name": "Jasa Besar", "offering_type": "service", "unit_price_idr": 10**15, "unit": "paket"},
        )
        self.assertEqual(s_off, 201)
        svc_id = d_off["item"]["offering_id"]

        # Derived revenue = 10**15 * 10000 = 10**19 (> 10**15) -> 422 value_overflow
        s_sale, d_sale = self._request(
            "POST",
            f"/v1/workspaces/{ws_a}/sales",
            token=self.token_a,
            body={"lines": [{"offering_id": svc_id, "qty": "10000"}]},
        )
        self.assertEqual(s_sale, 422)
        self.assertEqual(d_sale["code"], "value_overflow")
