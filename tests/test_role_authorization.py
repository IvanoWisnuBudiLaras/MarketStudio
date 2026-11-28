"""Comprehensive role authorization and state invariance tests for MarketStudio Issue #31.

Verifies role-based write permission checks on candidate write operation:
`POST /v1/workspaces/{id}/sales`:
1. Role Check on Write Operations:
   - Write-authorized roles (owner, operator, dsb.) successfully record sales (201 Created).
   - Read-only roles (viewer, read_only, dsb.) are rejected with 403 forbidden
     ("Akses ditolak: role ini tidak memiliki izin untuk mencatat transaksi.").
   - Service layer helpers (add_membership, set_membership_role, get_membership_role).
2. State Invariance (Zero Mutation on 403 Forbidden):
   - No records in sales or sale_lines.
   - No stock movements in stock_movements.
   - No cash movements in cash_movements.
   - No business audit events or idempotency keys consumed.
   - Repeated intent with same idempotency key is rejected 403 without mutation.
3. Anti-enumeration and tenant isolation:
   - Non-member -> 404 workspace_not_found (not 403).
   - Revoked member -> 404 workspace_not_found.
   - Unauthenticated -> 401 unauthenticated.
4. Multi-backend compatibility:
   - Identical invariants on SQLite default and live PostgreSQL 17.
"""

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

from app.db import db_transaction
from app.domain import DomainError, is_transaction_write_permitted
from app.migrations import apply_migrations
from app.server import create_server
from app.service import BaselineService

PG_TEST_URL = os.environ.get("MARKETSTUDIO_TEST_POSTGRES_URL", "").strip()


class RoleAuthorizationIntegrationTest(unittest.TestCase):
    """End-to-end HTTP and service role authorization tests (Issue #31) on SQLite."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "test_role_authorization.sqlite")
        self.server = create_server(host="127.0.0.1", port=0, db_path=self.db_path)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        # Login tokens for principals
        self.token_owner = self._login("actor_a", "dev-a-pass")
        self.token_operator = self._login("actor_operator", "dev-operator-pass")
        self.token_viewer = self._login("actor_viewer", "dev-viewer-pass")
        self.token_read_only = self._login("actor_b", "dev-b-pass")
        self.token_outsider = self._login("actor_c", "dev-c-pass")

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

    def _setup_test_workspace_with_inventory(self) -> tuple[str, str]:
        """Create a workspace, an offering, and initial stock via owner."""
        s_ws, ws = self._request("POST", "/v1/workspaces", {"name": "Warung Role Test"}, token=self.token_owner)
        self.assertEqual(s_ws, 201)
        ws_id = ws["item"]["workspace_id"]

        s_off, off = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Bakso Super", "offering_type": "goods", "unit_price_idr": 20000, "unit": "porsi"},
            token=self.token_owner,
        )
        self.assertEqual(s_off, 201)
        off_id = off["item"]["offering_id"]

        # Purchase 20 units @ 10,000 = 200,000
        s_pur, _ = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_id, "qty": "20", "total_cost_idr": 200000},
            token=self.token_owner,
        )
        self.assertEqual(s_pur, 201)
        return ws_id, off_id

    def test_owner_and_operator_authorized_to_create_sales(self) -> None:
        """Anggota berizin tulis (owner dan operator) berhasil mencatat transaksi penjualan (201 Created)."""
        ws_id, off_id = self._setup_test_workspace_with_inventory()

        # 1. Tambahkan actor_operator sebagai role 'operator'
        service = BaselineService(db_path=self.db_path)
        service.add_membership(ws_id, "actor_operator", role="operator")
        self.assertEqual(service.get_membership_role(ws_id, "actor_operator"), "operator")

        # 2. Operator mencatat penjualan -> Berhasil 201 Created
        sale_payload_op = {"lines": [{"offering_id": off_id, "qty": "3", "total_price_idr": 60000}]}
        s_op, res_op = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            sale_payload_op,
            token=self.token_operator,
        )
        self.assertEqual(s_op, 201)
        self.assertIn("sale_id", res_op["item"])
        self.assertEqual(res_op["item"]["total_revenue_idr"], 60000)
        self.assertEqual(res_op["item"]["total_cogs_idr"], 30000)  # 3 * 10,000 WA cost

        # 3. Owner mencatat penjualan -> Berhasil 201 Created
        sale_payload_owner = {"lines": [{"offering_id": off_id, "qty": "2", "total_price_idr": 40000}]}
        s_own, res_own = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            sale_payload_owner,
            token=self.token_owner,
        )
        self.assertEqual(s_own, 201)
        self.assertIn("sale_id", res_own["item"])
        self.assertEqual(res_own["item"]["total_revenue_idr"], 40000)

        # 4. Verifikasi laporan harian merefleksikan kedua penjualan (omzet = 100,000)
        s_rep, rep = self._request("GET", f"/v1/workspaces/{ws_id}/reports/daily", token=self.token_owner)
        self.assertEqual(s_rep, 200)
        self.assertEqual(rep["report"]["revenue_idr"], 100000)
        self.assertEqual(rep["report"]["cogs_idr"], 50000)

    def test_viewer_and_read_only_rejected_with_403_forbidden(self) -> None:
        """Anggota ber-role baca saja (viewer dan read_only) ditolak dengan 403 forbidden."""
        ws_id, off_id = self._setup_test_workspace_with_inventory()

        service = BaselineService(db_path=self.db_path)
        # Setup viewer dan read_only memberships
        service.add_membership(ws_id, "actor_viewer", role="viewer")
        service.add_membership(ws_id, "actor_b", role="read_only")
        self.assertEqual(service.get_membership_role(ws_id, "actor_viewer"), "viewer")
        self.assertEqual(service.get_membership_role(ws_id, "actor_b"), "read_only")

        # 1. Viewer mencoba mencatat penjualan -> 403 Forbidden
        sale_payload = {"lines": [{"offering_id": off_id, "qty": "1", "total_price_idr": 20000}]}
        s_v, res_v = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            sale_payload,
            token=self.token_viewer,
        )
        self.assertEqual(s_v, 403)
        self.assertEqual(res_v["code"], "forbidden")
        self.assertEqual(
            res_v["message"],
            "Akses ditolak: role ini tidak memiliki izin untuk mencatat transaksi.",
        )
        self.assertNotIn("item", res_v)

        # 2. Read_only mencoba mencatat penjualan -> 403 Forbidden
        s_ro, res_ro = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            sale_payload,
            token=self.token_read_only,
        )
        self.assertEqual(s_ro, 403)
        self.assertEqual(res_ro["code"], "forbidden")
        self.assertEqual(
            res_ro["message"],
            "Akses ditolak: role ini tidak memiliki izin untuk mencatat transaksi.",
        )
        self.assertNotIn("item", res_ro)

        # 3. Viewer dan read_only tetap DAPAT membaca data (read-only allowed)
        s_rep_v, _ = self._request("GET", f"/v1/workspaces/{ws_id}/reports/daily", token=self.token_viewer)
        self.assertEqual(s_rep_v, 200)

        s_rep_ro, _ = self._request("GET", f"/v1/workspaces/{ws_id}/reports/daily", token=self.token_read_only)
        self.assertEqual(s_rep_ro, 200)

    def test_zero_mutation_invariance_on_403_forbidden(self) -> None:
        """Invariansi State: penolakan 403 tidak menyebabkan mutasi pada sales, stock, cash, audit, atau idempotency."""
        ws_id, off_id = self._setup_test_workspace_with_inventory()

        service = BaselineService(db_path=self.db_path)
        service.add_membership(ws_id, "actor_viewer", role="viewer")

        # Snapshot kondisi database sebelum percobaan 403
        with service._tx() as conn:
            sales_before = conn.execute("SELECT COUNT(*) as c FROM sales WHERE workspace_id = ?", (ws_id,)).fetchone()["c"]
            lines_before = conn.execute("SELECT COUNT(*) as c FROM sale_lines WHERE workspace_id = ?", (ws_id,)).fetchone()["c"]
            stock_mov_before = conn.execute("SELECT COUNT(*) as c FROM stock_movements WHERE workspace_id = ?", (ws_id,)).fetchone()["c"]
            cash_mov_before = conn.execute("SELECT COUNT(*) as c FROM cash_movements WHERE workspace_id = ?", (ws_id,)).fetchone()["c"]
            audit_before = conn.execute("SELECT COUNT(*) as c FROM audit_events WHERE workspace_id = ?", (ws_id,)).fetchone()["c"]
            idem_before = conn.execute("SELECT COUNT(*) as c FROM idempotency_keys WHERE workspace_id = ?", (ws_id,)).fetchone()["c"]
            pool_before = conn.execute(
                "SELECT qty_on_hand, total_value_idr FROM inventory_pools WHERE workspace_id = ? AND offering_id = ?",
                (ws_id, off_id),
            ).fetchone()
            qty_before = pool_before["qty_on_hand"]
            val_before = pool_before["total_value_idr"]

        # Viewer mengirim request penjualan dengan Idempotency-Key
        idem_key = "idem-viewer-forbidden-001"
        sale_payload = {"lines": [{"offering_id": off_id, "qty": "5", "total_price_idr": 100000}]}
        status, res = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            sale_payload,
            headers={"Idempotency-Key": idem_key},
            token=self.token_viewer,
        )
        self.assertEqual(status, 403)
        self.assertEqual(res["code"], "forbidden")

        # Snapshot kondisi database setelah penolakan 403 -> Harus IDENTIK (Zero Mutation)
        with service._tx() as conn:
            sales_after = conn.execute("SELECT COUNT(*) as c FROM sales WHERE workspace_id = ?", (ws_id,)).fetchone()["c"]
            lines_after = conn.execute("SELECT COUNT(*) as c FROM sale_lines WHERE workspace_id = ?", (ws_id,)).fetchone()["c"]
            stock_mov_after = conn.execute("SELECT COUNT(*) as c FROM stock_movements WHERE workspace_id = ?", (ws_id,)).fetchone()["c"]
            cash_mov_after = conn.execute("SELECT COUNT(*) as c FROM cash_movements WHERE workspace_id = ?", (ws_id,)).fetchone()["c"]
            audit_after = conn.execute("SELECT COUNT(*) as c FROM audit_events WHERE workspace_id = ?", (ws_id,)).fetchone()["c"]
            idem_after = conn.execute("SELECT COUNT(*) as c FROM idempotency_keys WHERE workspace_id = ?", (ws_id,)).fetchone()["c"]
            pool_after = conn.execute(
                "SELECT qty_on_hand, total_value_idr FROM inventory_pools WHERE workspace_id = ? AND offering_id = ?",
                (ws_id, off_id),
            ).fetchone()

        self.assertEqual(sales_after, sales_before, "Tabel sales tidak boleh bertambah saat 403")
        self.assertEqual(lines_after, lines_before, "Tabel sale_lines tidak boleh bertambah saat 403")
        self.assertEqual(stock_mov_after, stock_mov_before, "Tabel stock_movements tidak boleh bertambah saat 403")
        self.assertEqual(cash_mov_after, cash_mov_before, "Tabel cash_movements tidak boleh bertambah saat 403")
        self.assertEqual(audit_after, audit_before, "Audit log bisnis tidak boleh terkonsumsi saat 403")
        self.assertEqual(idem_after, idem_before, "Idempotency key tidak boleh terkonsumsi/tersimpan saat 403")
        self.assertEqual(pool_after["qty_on_hand"], qty_before, "Stok persediaan tidak boleh berkurang saat 403")
        self.assertEqual(pool_after["total_value_idr"], val_before, "Nilai persediaan tidak boleh berubah saat 403")

    def test_idempotency_intent_repetition_rejected_without_mutation(self) -> None:
        """Pengulangan intent (idempotency key yang sama) tetap ditolak 403 tanpa mutasi state."""
        ws_id, off_id = self._setup_test_workspace_with_inventory()

        service = BaselineService(db_path=self.db_path)
        service.add_membership(ws_id, "actor_viewer", role="viewer")

        idem_key = "idem-repeat-intent-test"
        sale_payload = {"lines": [{"offering_id": off_id, "qty": "2", "total_price_idr": 40000}]}

        # Percobaan 1: 403
        s1, res1 = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            sale_payload,
            headers={"Idempotency-Key": idem_key},
            token=self.token_viewer,
        )
        self.assertEqual(s1, 403)
        self.assertEqual(res1["code"], "forbidden")

        # Percobaan 2: Replay intent dengan key yang sama -> Tetap 403
        s2, res2 = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            sale_payload,
            headers={"Idempotency-Key": idem_key},
            token=self.token_viewer,
        )
        self.assertEqual(s2, 403)
        self.assertEqual(res2["code"], "forbidden")

        # Verifikasi idempotency key tidak terkonsumsi di DB
        with service._tx() as conn:
            key_row = conn.execute(
                "SELECT * FROM idempotency_keys WHERE workspace_id = ? AND idempotency_key = ?",
                (ws_id, idem_key),
            ).fetchone()
            self.assertIsNone(key_row, "Key yang ditolak 403 tidak boleh disimpan di idempotency_keys")

        # Bukti: Anggota berizin tulis (owner) dapat menggunakan key tersebut untuk transaksi sah
        s_owner, res_owner = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            sale_payload,
            headers={"Idempotency-Key": idem_key},
            token=self.token_owner,
        )
        self.assertEqual(s_owner, 201)
        self.assertIn("sale_id", res_owner["item"])

    def test_non_member_and_revoked_actor_isolation(self) -> None:
        """Non-member dan revoked member ditolak 404 (bukan 403) untuk anti-enumeration."""
        ws_id, off_id = self._setup_test_workspace_with_inventory()

        sale_payload = {"lines": [{"offering_id": off_id, "qty": "1", "total_price_idr": 20000}]}

        # 1. Non-member (actor_outsider) -> 404 workspace_not_found (tidak membocorkan status role 403)
        s_out, res_out = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            sale_payload,
            token=self.token_outsider,
        )
        self.assertEqual(s_out, 404)
        self.assertEqual(res_out["code"], "workspace_not_found")

        # 2. Member yang dicabut (revoked) -> 404 workspace_not_found
        service = BaselineService(db_path=self.db_path)
        service.add_membership(ws_id, "actor_viewer", role="viewer")
        service.revoke_membership(ws_id, "actor_viewer")

        s_rev, res_rev = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            sale_payload,
            token=self.token_viewer,
        )
        self.assertEqual(s_rev, 404)
        self.assertEqual(res_rev["code"], "workspace_not_found")

        # 3. Tanpa token autentikasi -> 401 unauthenticated
        s_anon, res_anon = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            sale_payload,
        )
        self.assertEqual(s_anon, 401)
        self.assertEqual(res_anon["code"], "unauthenticated")

    def test_service_layer_role_management_and_transitions(self) -> None:
        """Memverifikasi helper service layer (set_membership_role, get_membership_role) dan transisi dinamis role."""
        service = BaselineService(db_path=self.db_path)
        _, ws = service.create_workspace({"name": "Role Lifecycle WS"}, actor="actor_a")
        ws_id = ws["workspace_id"]

        _, off = service.create_offering(
            ws_id,
            actor_id="actor_a",
            payload={"name": "Teh Manis", "offering_type": "goods", "unit_price_idr": 5000, "unit": "gelas"},
            actor="actor_a",
        )
        off_id = off["offering_id"]

        service.create_purchase(
            ws_id,
            actor_id="actor_a",
            payload={"offering_id": off_id, "qty": "10", "total_cost_idr": 25000},
            actor="actor_a",
        )

        # 1. Tambah actor_viewer sebagai 'viewer'
        service.set_membership_role(ws_id, "actor_viewer", "viewer")
        self.assertEqual(service.get_membership_role(ws_id, "actor_viewer"), "viewer")

        # Mencatat penjualan ditolak 403
        sale_data = {"lines": [{"offering_id": off_id, "qty": "1", "total_price_idr": 5000}]}
        with self.assertRaises(DomainError) as ctx_v:
            service.create_sale(ws_id, actor_id="actor_viewer", payload=sale_data, actor="actor_viewer")
        self.assertEqual(ctx_v.exception.status_code, 403)
        self.assertEqual(ctx_v.exception.code, "forbidden")
        self.assertEqual(ctx_v.exception.message, "Akses ditolak: role ini tidak memiliki izin untuk mencatat transaksi.")

        # 2. Promosikan actor_viewer menjadi 'operator'
        service.set_membership_role(ws_id, "actor_viewer", "operator")
        self.assertEqual(service.get_membership_role(ws_id, "actor_viewer"), "operator")

        # Sekarang berhasil mencatat penjualan 201 Created
        status_op, res_op = service.create_sale(ws_id, actor_id="actor_viewer", payload=sale_data, actor="actor_viewer")
        self.assertEqual(status_op, 201)
        self.assertIn("sale_id", res_op)

        # 3. Turunkan kembali ke 'read_only'
        service.set_membership_role(ws_id, "actor_viewer", "read_only")
        self.assertEqual(service.get_membership_role(ws_id, "actor_viewer"), "read_only")

        # Kembali ditolak 403
        with self.assertRaises(DomainError) as ctx_ro:
            service.create_sale(ws_id, actor_id="actor_viewer", payload=sale_data, actor="actor_viewer")
        self.assertEqual(ctx_ro.exception.status_code, 403)
        self.assertEqual(ctx_ro.exception.code, "forbidden")

    def test_domain_helper_is_transaction_write_permitted(self) -> None:
        """Uji fungsi otorisasi domain is_transaction_write_permitted untuk berbagai role."""
        # Write-authorized roles
        self.assertTrue(is_transaction_write_permitted("owner"))
        self.assertTrue(is_transaction_write_permitted("operator"))
        self.assertTrue(is_transaction_write_permitted("admin"))
        self.assertTrue(is_transaction_write_permitted("manager"))
        self.assertTrue(is_transaction_write_permitted("cashier"))
        self.assertTrue(is_transaction_write_permitted("staff"))
        self.assertTrue(is_transaction_write_permitted("member"))
        self.assertTrue(is_transaction_write_permitted("  OWNER  "))
        self.assertTrue(is_transaction_write_permitted("Operator"))

        # Read-only roles
        self.assertFalse(is_transaction_write_permitted("viewer"))
        self.assertFalse(is_transaction_write_permitted("read_only"))
        self.assertFalse(is_transaction_write_permitted("readonly"))
        self.assertFalse(is_transaction_write_permitted("auditor"))
        self.assertFalse(is_transaction_write_permitted("guest"))
        self.assertFalse(is_transaction_write_permitted("  VIEWER  "))
        self.assertFalse(is_transaction_write_permitted("Read_Only"))

        # Invalid / unknown roles
        self.assertFalse(is_transaction_write_permitted(None))
        self.assertFalse(is_transaction_write_permitted(""))
        self.assertFalse(is_transaction_write_permitted("unknown_role"))
        self.assertFalse(is_transaction_write_permitted("hacker"))


@unittest.skipUnless(PG_TEST_URL, "Set MARKETSTUDIO_TEST_POSTGRES_URL to run live PostgreSQL 17 integration tests")
class PostgresRoleAuthorizationTest(unittest.TestCase):
    """PostgreSQL 17 live integration test for Issue #31 role authorization and state invariance."""

    _DOMAIN_TABLES = (
        "pricing_decisions",
        "audit_events",
        "idempotency_keys",
        "cash_movements",
        "sale_lines",
        "sales",
        "stock_movements",
        "inventory_pools",
        "inventory_batches",
        "purchases",
        "offerings",
        "workspace_memberships",
        "workspaces",
        "sessions",
    )

    def setUp(self) -> None:
        self.pg_url = PG_TEST_URL
        apply_migrations(self.pg_url)
        with db_transaction(database_url=self.pg_url) as conn:
            conn.execute(f"TRUNCATE TABLE {', '.join(self._DOMAIN_TABLES)}")
        self.server = create_server(host="127.0.0.1", port=0, database_url=self.pg_url, auto_migrate=False)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        self.token_owner = self._login("actor_a", "dev-a-pass")
        self.token_operator = self._login("actor_operator", "dev-operator-pass")
        self.token_viewer = self._login("actor_viewer", "dev-viewer-pass")

    def tearDown(self) -> None:
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

    def test_pg_role_authorization_and_state_invariance(self) -> None:
        """Verifikasi otorisasi role dan invariansi state pada PostgreSQL 17."""
        # 1. Setup workspace dan persediaan oleh owner
        _, ws = self._request("POST", "/v1/workspaces", {"name": "Warung PG Role"}, token=self.token_owner)
        ws_id = ws["item"]["workspace_id"]

        _, off = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Soto Ayam PG", "offering_type": "goods", "unit_price_idr": 18000, "unit": "mangkuk"},
            token=self.token_owner,
        )
        off_id = off["item"]["offering_id"]

        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_id, "qty": "10", "total_cost_idr": 100000},
            token=self.token_owner,
        )

        # 2. Tambah operator dan viewer
        service = BaselineService(database_url=self.pg_url)
        service.set_membership_role(ws_id, "actor_operator", "operator")
        service.set_membership_role(ws_id, "actor_viewer", "viewer")

        # 3. Viewer mencoba catat penjualan -> Ditolak 403 Forbidden
        sale_payload = {"lines": [{"offering_id": off_id, "qty": "2", "total_price_idr": 36000}]}
        s_v, res_v = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            sale_payload,
            headers={"Idempotency-Key": "pg-viewer-sale-001"},
            token=self.token_viewer,
        )
        self.assertEqual(s_v, 403)
        self.assertEqual(res_v["code"], "forbidden")
        self.assertEqual(
            res_v["message"],
            "Akses ditolak: role ini tidak memiliki izin untuk mencatat transaksi.",
        )

        # Bukti invariansi di Postgres: 0 sales, 0 idempotency key
        with db_transaction(database_url=self.pg_url) as conn:
            sales_cnt = conn.execute("SELECT COUNT(*) as c FROM sales WHERE workspace_id = ?", (ws_id,)).fetchone()["c"]
            idem_cnt = conn.execute("SELECT COUNT(*) as c FROM idempotency_keys WHERE workspace_id = ?", (ws_id,)).fetchone()["c"]
            self.assertEqual(sales_cnt, 0)
            self.assertEqual(idem_cnt, 0)

        # 4. Operator mencatat penjualan -> Berhasil 201 Created
        s_op, res_op = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            sale_payload,
            token=self.token_operator,
        )
        self.assertEqual(s_op, 201)
        self.assertIn("sale_id", res_op["item"])
        self.assertEqual(res_op["item"]["total_revenue_idr"], 36000)
