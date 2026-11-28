"""Comprehensive tenant isolation tests for MarketStudio Issue #6.

Verifies and proves rejection of cross-workspace data access:
- Active member: 200 OK with accurate daily report data.
- Non-member (actor without membership): 404 workspace_not_found without data leakage.
- Revoked member: 404 workspace_not_found without data, even with existing pre-revocation session.
- Unauthenticated (no token / invalid token): 401 unauthenticated.
- Anti-enumeration: identical 404 for existing workspace non-member vs non-existent workspace.
- Dual profile: SQLite default and PostgreSQL (when URL available).
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

from app.db import db_transaction, init_db
from app.domain import DomainError
from app.migrations import apply_migrations
from app.server import create_server
from app.service import BaselineService

PG_TEST_URL = os.environ.get("MARKETSTUDIO_TEST_POSTGRES_URL", "").strip()


class TenantIsolationIntegrationTest(unittest.TestCase):
    """End-to-end HTTP and service tenant isolation verification (Issue #6) on SQLite."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "test_tenant_isolation.sqlite")
        self.server = create_server(host="127.0.0.1", port=0, db_path=self.db_path)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        # Login tokens
        self.token_a = self._login("actor_a", "dev-a-pass")
        self.token_b = self._login("actor_b", "dev-b-pass")
        self.token_c = self._login("actor_c", "dev-c-pass")

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

    def test_issue_6_daily_report_tenant_isolation_lifecycle(self) -> None:
        """Skenario Utama Issue #6:
        1. Aktor A (owner workspace 1) baca workspace 1 -> 200 OK dengan data akurat.
        2. Aktor B (owner workspace 2) baca workspace 1 -> 404 tanpa data bocor.
        3. Aktor C bergabung ke workspace 1 -> buat sesi -> verifikasi baca 200 OK.
        4. Membership Aktor C dicabut (revoked_at diset) -> Aktor C baca dengan sesi lama -> 404 tanpa data.
        5. Aktor anonim/tanpa token -> 401 unauthenticated.
        """
        # 1. Setup Workspace 1 oleh Aktor A dengan data finansial nyata
        s_ws1, ws1 = self._request("POST", "/v1/workspaces", {"name": "Warung Kopi A"}, token=self.token_a)
        self.assertEqual(s_ws1, 201)
        ws1_id = ws1["item"]["workspace_id"]

        # Tambah offering barang & stok di Workspace 1
        _, off1 = self._request(
            "POST",
            f"/v1/workspaces/{ws1_id}/offerings",
            {"name": "Kopi Tubruk", "offering_type": "goods", "unit_price_idr": 15000, "unit": "cup"},
            token=self.token_a,
        )
        off1_id = off1["item"]["offering_id"]

        # Pembelian stok: 10 cup @ 5000 = 50000
        self._request(
            "POST",
            f"/v1/workspaces/{ws1_id}/purchases",
            {"offering_id": off1_id, "qty": "10", "total_cost_idr": 50000},
            token=self.token_a,
        )

        # Penjualan: 4 cup @ 15000 = 60000 (HPP = 20000, Laba Kotor = 40000)
        self._request(
            "POST",
            f"/v1/workspaces/{ws1_id}/sales",
            {"lines": [{"offering_id": off1_id, "qty": "4", "total_price_idr": 60000}]},
            token=self.token_a,
        )

        # Verifikasi 1: Aktor A (owner sah) membaca laporan harian -> 200 OK
        s_rep_a, rep_a = self._request("GET", f"/v1/workspaces/{ws1_id}/reports/daily", token=self.token_a)
        self.assertEqual(s_rep_a, 200)
        self.assertIn("report", rep_a)
        self.assertEqual(rep_a["report"]["revenue_idr"], 60000)
        self.assertEqual(rep_a["report"]["cogs_idr"], 20000)
        self.assertEqual(rep_a["report"]["gross_profit_idr"], 40000)
        self.assertEqual(rep_a["report"]["cogs_status"], "assessed")
        self.assertEqual(rep_a["report"]["gross_profit_status"], "assessed")

        # 2. Setup Workspace 2 oleh Aktor B
        s_ws2, ws2 = self._request("POST", "/v1/workspaces", {"name": "Toko Buku B"}, token=self.token_b)
        self.assertEqual(s_ws2, 201)
        ws2_id = ws2["item"]["workspace_id"]

        # Verifikasi 2: Aktor B (non-anggota Workspace 1) mencoba membaca laporan harian Workspace 1 -> 404
        s_rep_b, rep_b = self._request("GET", f"/v1/workspaces/{ws1_id}/reports/daily", token=self.token_b)
        self.assertEqual(s_rep_b, 404)
        self.assertEqual(rep_b["code"], "workspace_not_found")
        self.assertNotIn("report", rep_b)
        self.assertNotIn("revenue_idr", json.dumps(rep_b))

        # Verifikasi isolasi timbal-balik: Laporan Workspace 2 milik Aktor B tetap 0 dan tidak terpengaruh Workspace 1
        s_rep_b_own, rep_b_own = self._request("GET", f"/v1/workspaces/{ws2_id}/reports/daily", token=self.token_b)
        self.assertEqual(s_rep_b_own, 200)
        self.assertEqual(rep_b_own["report"]["revenue_idr"], 0)
        self.assertEqual(rep_b_own["report"]["cogs_idr"], 0)

        # 3. Aktor C bergabung ke Workspace 1 sebagai member
        service = BaselineService(db_path=self.db_path)
        service.add_membership(ws1_id, "actor_c", role="member")

        # Verifikasi 3: Aktor C (anggota aktif) membaca laporan harian Workspace 1 -> 200 OK dengan data akurat
        s_rep_c, rep_c = self._request("GET", f"/v1/workspaces/{ws1_id}/reports/daily", token=self.token_c)
        self.assertEqual(s_rep_c, 200)
        self.assertEqual(rep_c["report"]["revenue_idr"], 60000)
        self.assertEqual(rep_c["report"]["cogs_idr"], 20000)
        self.assertEqual(rep_c["report"]["gross_profit_idr"], 40000)

        # 4. Membership Aktor C dicabut (revoked_at diset)
        service.revoke_membership(ws1_id, "actor_c")

        # Verifikasi 4: Aktor C melakukan request dengan sesi lama (dibuat sebelum pencabutan) -> ditolak 404
        s_rep_c_rev, rep_c_rev = self._request("GET", f"/v1/workspaces/{ws1_id}/reports/daily", token=self.token_c)
        self.assertEqual(s_rep_c_rev, 404)
        self.assertEqual(rep_c_rev["code"], "workspace_not_found")
        self.assertNotIn("report", rep_c_rev)
        self.assertNotIn("revenue_idr", json.dumps(rep_c_rev))

        # 5. Verifikasi 5: Aktor anonim/tanpa token -> 401 unauthenticated
        s_unauth, rep_unauth = self._request("GET", f"/v1/workspaces/{ws1_id}/reports/daily")
        self.assertEqual(s_unauth, 401)
        self.assertEqual(rep_unauth["code"], "unauthenticated")
        self.assertNotIn("report", rep_unauth)

        # Token palsu / invalid -> 401 unauthenticated
        s_fake, rep_fake = self._request(
            "GET", f"/v1/workspaces/{ws1_id}/reports/daily", headers={"Authorization": "Bearer invalid_token_xyz"}
        )
        self.assertEqual(s_fake, 401)
        self.assertEqual(rep_fake["code"], "unauthenticated")

    def test_anti_enumeration_non_member_vs_unknown_workspace(self) -> None:
        """Respon 404 untuk workspace yang ada (tetapi aktor bukan anggota) harus identik
        dengan workspace yang memang tidak pernah ada, guna mencegah kebocoran informasi (anti-enumeration).
        """
        _, ws_a = self._request("POST", "/v1/workspaces", {"name": "WS Secret"}, token=self.token_a)
        ws_real_id = ws_a["item"]["workspace_id"]
        ws_fake_id = "ws_nonexistent_99999"

        # Non-member pada workspace nyata
        s_nm, e_nm = self._request("GET", f"/v1/workspaces/{ws_real_id}/reports/daily", token=self.token_b)
        self.assertEqual(s_nm, 404)
        self.assertEqual(e_nm["code"], "workspace_not_found")

        # Aktor pada workspace fiktif
        s_fk, e_fk = self._request("GET", f"/v1/workspaces/{ws_fake_id}/reports/daily", token=self.token_b)
        self.assertEqual(s_fk, 404)
        self.assertEqual(e_fk["code"], "workspace_not_found")
        self.assertEqual(e_nm["message"], e_fk["message"])

    def test_multi_route_read_isolation_for_non_member_and_revoked(self) -> None:
        """Memverifikasi bahwa seluruh operasi baca data workspace menolak non-anggota,
        anggota dicabut, dan aktor tanpa autentikasi secara konsisten.
        """
        _, ws = self._request("POST", "/v1/workspaces", {"name": "WS Multi Read"}, token=self.token_a)
        ws_id = ws["item"]["workspace_id"]
        _, off = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Barang Multi", "offering_type": "goods", "unit_price_idr": 10000},
            token=self.token_a,
        )
        off_id = off["item"]["offering_id"]

        read_routes = [
            ("GET", f"/v1/workspaces/{ws_id}/reports/daily"),
            ("GET", f"/v1/workspaces/{ws_id}/offerings"),
            ("GET", f"/v1/workspaces/{ws_id}/offerings/{off_id}"),
        ]

        # 1. Non-member (Aktor B) ditolak 404
        for method, path in read_routes:
            status, err = self._request(method, path, token=self.token_b)
            self.assertEqual(status, 404, f"Aktor B should be rejected 404 on {path}")
            self.assertEqual(err["code"], "workspace_not_found")

        # 2. Anggota dicabut (Aktor C) ditolak 404
        service = BaselineService(db_path=self.db_path)
        service.add_membership(ws_id, "actor_c", role="member")
        # Sukses baca saat aktif
        for method, path in read_routes:
            status, _ = self._request(method, path, token=self.token_c)
            self.assertEqual(status, 200, f"Aktor C should read 200 on {path} while active")

        # Revoke Aktor C
        service.revoke_membership(ws_id, "actor_c")
        for method, path in read_routes:
            status, err = self._request(method, path, token=self.token_c)
            self.assertEqual(status, 404, f"Aktor C should be rejected 404 on {path} after revoke")
            self.assertEqual(err["code"], "workspace_not_found")

        # 3. Unauthenticated ditolak 401
        for method, path in read_routes:
            status, err = self._request(method, path)
            self.assertEqual(status, 401, f"Unauthenticated request should be rejected 401 on {path}")
            self.assertEqual(err["code"], "unauthenticated")

    def test_direct_service_layer_rejection(self) -> None:
        """Memverifikasi penolakan pada tingkat service layer langsung (BaselineService._assert_workspace_access)."""
        service = BaselineService(db_path=self.db_path)
        _, ws = service.create_workspace({"name": "Service Isolation WS"}, actor="actor_a")
        ws_id = ws["workspace_id"]

        # 1. Unauthenticated (actor_id=None atau kosong) -> 401
        with self.assertRaises(DomainError) as ctx_none:
            service.get_daily_report(ws_id, actor_id=None)
        self.assertEqual(ctx_none.exception.status_code, 401)
        self.assertEqual(ctx_none.exception.code, "unauthenticated")

        with self.assertRaises(DomainError) as ctx_empty:
            service.get_daily_report(ws_id, actor_id="")
        self.assertEqual(ctx_empty.exception.status_code, 401)
        self.assertEqual(ctx_empty.exception.code, "unauthenticated")

        # 2. Non-member (actor_b) -> 404
        with self.assertRaises(DomainError) as ctx_b:
            service.get_daily_report(ws_id, actor_id="actor_b")
        self.assertEqual(ctx_b.exception.status_code, 404)
        self.assertEqual(ctx_b.exception.code, "workspace_not_found")

        # 3. Anggota aktif -> 200
        service.add_membership(ws_id, "actor_c", role="member")
        rep = service.get_daily_report(ws_id, actor_id="actor_c")
        self.assertIsInstance(rep, dict)
        self.assertEqual(rep["revenue_idr"], 0)

        # 4. Anggota dicabut -> 404
        service.revoke_membership(ws_id, "actor_c")
        with self.assertRaises(DomainError) as ctx_c:
            service.get_daily_report(ws_id, actor_id="actor_c")
        self.assertEqual(ctx_c.exception.status_code, 404)
        self.assertEqual(ctx_c.exception.code, "workspace_not_found")


@unittest.skipUnless(PG_TEST_URL, "Set MARKETSTUDIO_TEST_POSTGRES_URL to run live PostgreSQL 17 integration tests")
class PostgresTenantIsolationIntegrationTest(unittest.TestCase):
    """PostgreSQL 17 tenant isolation verification (Issue #6)."""

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

        self.token_a = self._login("actor_a", "dev-a-pass")
        self.token_b = self._login("actor_b", "dev-b-pass")
        self.token_c = self._login("actor_c", "dev-c-pass")

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

    def test_pg_issue_6_daily_report_tenant_isolation_lifecycle(self) -> None:
        """Skenario Issue #6 pada PostgreSQL 17."""
        # Setup WS 1 oleh Aktor A
        _, ws1 = self._request("POST", "/v1/workspaces", {"name": "Warung PG A"}, token=self.token_a)
        ws1_id = ws1["item"]["workspace_id"]

        _, off1 = self._request(
            "POST",
            f"/v1/workspaces/{ws1_id}/offerings",
            {"name": "Bakso Urat", "offering_type": "goods", "unit_price_idr": 20000, "unit": "porsi"},
            token=self.token_a,
        )
        off1_id = off1["item"]["offering_id"]

        self._request(
            "POST",
            f"/v1/workspaces/{ws1_id}/purchases",
            {"offering_id": off1_id, "qty": "5", "total_cost_idr": 50000},
            token=self.token_a,
        )
        self._request(
            "POST",
            f"/v1/workspaces/{ws1_id}/sales",
            {"lines": [{"offering_id": off1_id, "qty": "2", "total_price_idr": 40000}]},
            token=self.token_a,
        )

        # 1. Aktor A baca WS 1 -> 200 OK
        s_rep_a, rep_a = self._request("GET", f"/v1/workspaces/{ws1_id}/reports/daily", token=self.token_a)
        self.assertEqual(s_rep_a, 200)
        self.assertEqual(rep_a["report"]["revenue_idr"], 40000)
        self.assertEqual(rep_a["report"]["cogs_idr"], 20000)
        self.assertEqual(rep_a["report"]["gross_profit_idr"], 20000)

        # 2. Aktor B baca WS 1 -> 404
        s_rep_b, rep_b = self._request("GET", f"/v1/workspaces/{ws1_id}/reports/daily", token=self.token_b)
        self.assertEqual(s_rep_b, 404)
        self.assertEqual(rep_b["code"], "workspace_not_found")
        self.assertNotIn("report", rep_b)

        # 3. Aktor C bergabung ke WS 1 -> buat sesi -> verifikasi baca 200 OK
        service = BaselineService(database_url=self.pg_url)
        service.add_membership(ws1_id, "actor_c", role="member")

        s_rep_c, rep_c = self._request("GET", f"/v1/workspaces/{ws1_id}/reports/daily", token=self.token_c)
        self.assertEqual(s_rep_c, 200)
        self.assertEqual(rep_c["report"]["revenue_idr"], 40000)

        # 4. Membership Aktor C dicabut -> Aktor C request baca dengan sesi lama -> 404
        service.revoke_membership(ws1_id, "actor_c")
        s_rep_c_rev, rep_c_rev = self._request("GET", f"/v1/workspaces/{ws1_id}/reports/daily", token=self.token_c)
        self.assertEqual(s_rep_c_rev, 404)
        self.assertEqual(rep_c_rev["code"], "workspace_not_found")

        # 5. Anonim -> 401 unauthenticated
        s_unauth, rep_unauth = self._request("GET", f"/v1/workspaces/{ws1_id}/reports/daily")
        self.assertEqual(s_unauth, 401)
        self.assertEqual(rep_unauth["code"], "unauthenticated")
