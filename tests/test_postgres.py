"""Unit and isolated PostgreSQL 17 integration tests for MarketStudio Issue #54."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit, urlunsplit

os.environ["MARKETSTUDIO_QUIET_LOGS"] = "1"

from app.db import (  # noqa: E402
    DatabaseConfig,
    DbRow,
    db_transaction,
    init_db,
    is_postgres_dsn,
    redact_dsn,
    resolve_db_config,
    translate_qmark_to_pyformat,
)
from app.domain import DomainError  # noqa: E402
from app.migrations import (  # noqa: E402
    MigrationError,
    apply_migrations,
    discover_migrations,
    get_migration_status,
    rollback_migrations,
    verify_migrations_current,
)
from app.server import create_server  # noqa: E402
from app.service import BaselineService  # noqa: E402

PG_TEST_URL = os.environ.get("MARKETSTUDIO_TEST_POSTGRES_URL", "").strip()


class PostgresAdapterUnitTest(unittest.TestCase):
    """Dependency-free unit tests for env resolution, DSN redaction, SQL translation, and migrations."""

    def test_resolve_db_config_defaults_and_overrides(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg_default = resolve_db_config()
            self.assertEqual(cfg_default.backend, "sqlite")
            self.assertTrue(cfg_default.target.endswith("marketstudio.db"))

        # Explicit SQLite path overrides MARKETSTUDIO_DB_BACKEND=postgres
        with mock.patch.dict(
            os.environ,
            {"MARKETSTUDIO_DB_BACKEND": "postgres", "DATABASE_URL": "postgresql://u:p@localhost:5432/db"},
            clear=True,
        ):
            cfg_explicit_sqlite = resolve_db_config(db_path="/tmp/test_override.db")
            self.assertEqual(cfg_explicit_sqlite.backend, "sqlite")
            self.assertEqual(cfg_explicit_sqlite.target, "/tmp/test_override.db")

        # Explicit postgres backend without DATABASE_URL fails loudly (no silent fallback)
        with mock.patch.dict(os.environ, {"MARKETSTUDIO_DB_BACKEND": "postgres"}, clear=True):
            with self.assertRaises(ValueError):
                resolve_db_config()

        # Unknown backend fails loudly
        with mock.patch.dict(os.environ, {"MARKETSTUDIO_DB_BACKEND": "mysql"}, clear=True):
            with self.assertRaises(ValueError):
                resolve_db_config()

        # Remote host defaults sslmode=require and auto_migrate respects production env
        with mock.patch.dict(
            os.environ,
            {
                "MARKETSTUDIO_DB_BACKEND": "postgres",
                "DATABASE_URL": "postgresql://svc:secret@db.example.supabase.co:6543/postgres",
                "MARKETSTUDIO_ENV": "production",
            },
            clear=True,
        ):
            cfg_remote = resolve_db_config()
            self.assertEqual(cfg_remote.backend, "postgres")
            self.assertEqual(cfg_remote.sslmode, "require")
            self.assertIsNone(cfg_remote.prepare_threshold)
            self.assertFalse(cfg_remote.auto_migrate)

        # Localhost skips sslmode=require unless requested
        cfg_local = resolve_db_config(database_url="postgresql://admin:pw@127.0.0.1:55432/ms_test")
        self.assertEqual(cfg_local.backend, "postgres")
        self.assertIsNone(cfg_local.sslmode)
        self.assertTrue(is_postgres_dsn(cfg_local.target))

    def test_redact_dsn_masks_credentials(self) -> None:
        raw = "postgresql://secret_user:super_secret_pw@db.example.com:6543/postgres?sslmode=require&password=inline_pw"
        redacted = redact_dsn(raw)
        self.assertNotIn("secret_user", redacted)
        self.assertNotIn("super_secret_pw", redacted)
        self.assertNotIn("inline_pw", redacted)
        self.assertIn("db.example.com:6543/postgres", redacted)
        self.assertIn("sslmode=require", redacted)
        self.assertIn("***@", redacted)
        self.assertEqual(redact_dsn("data/marketstudio.db"), "data/marketstudio.db")

    def test_translate_qmark_to_pyformat(self) -> None:
        sql = (
            "SELECT \"col?%\" FROM t -- comment with ? and 50%\n"
            "WHERE a = ? /* nested /* ? 10% */ comment */ AND b = 'it''s 100% ok?' AND c LIKE '%x%' AND d = ?"
        )
        translated = translate_qmark_to_pyformat(sql)
        expected = (
            "SELECT \"col?%%\" FROM t -- comment with ? and 50%%\n"
            "WHERE a = %s /* nested /* ? 10%% */ comment */ AND b = 'it''s 100%% ok?' AND c LIKE '%%x%%' AND d = %s"
        )
        self.assertEqual(translated, expected)

    def test_db_row_contract(self) -> None:
        row = DbRow(
            ["qty", "zero_qty", "micro_qty", "occurred_at", "total_idr"],
            [
                Decimal("2.50"),
                Decimal("0.00"),
                Decimal("0.0000000000000001"),
                datetime(2026, 11, 27, 17, 0, 0, tzinfo=timezone(timedelta(hours=7))),
                15000,
            ],
        )
        self.assertEqual(row["qty"], "2.5")
        self.assertEqual(row["zero_qty"], "0")
        self.assertEqual(row["micro_qty"], "0.0000000000000001")
        self.assertEqual(row["occurred_at"], "2026-11-27T10:00:00+00:00")
        self.assertEqual(row[4], 15000)
        as_dict = dict(row)
        self.assertEqual(as_dict["qty"], "2.5")
        q, z, m, ts, tot = row
        self.assertEqual((q, z, m, ts, tot), ("2.5", "0", "0.0000000000000001", "2026-11-27T10:00:00+00:00", 15000))

    def test_discover_migrations_valid(self) -> None:
        specs = discover_migrations()
        self.assertEqual([s.version for s in specs], ["0001", "0002", "0003", "0004"])
        self.assertEqual(specs[0].name, "initial_schema")
        self.assertEqual(specs[1].name, "rls_and_service_privileges")
        self.assertEqual(specs[3].name, "offering_pricing_and_archive")
        for spec in specs:
            self.assertTrue(spec.up_path.is_file())
            self.assertTrue(spec.down_path.is_file())
            self.assertEqual(len(spec.checksum), 64)


def _replace_dsn_credentials(dsn: str, username: str, password: str) -> str:
    parts = urlsplit(dsn)
    host = parts.hostname or "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port is not None else ""
    netloc = f"{username}:{password}@{host}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


@unittest.skipUnless(PG_TEST_URL, "Set MARKETSTUDIO_TEST_POSTGRES_URL to run live PostgreSQL 17 integration tests")
class PostgresIntegrationTest(unittest.TestCase):
    """Full end-to-end verification against an isolated local PostgreSQL 17 database."""

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

    def tearDown(self) -> None:
        self._stop_server()

    def _stop_server(self) -> None:
        if getattr(self, "server", None) is not None:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=2)
            self.server = None

    def _login(self, actor_id: str, passcode: str, base_url: str | None = None) -> str:
        status, res = self._request(
            "POST",
            "/v1/sessions",
            {"actor_id": actor_id, "passcode": passcode},
            base_url=base_url,
        )
        self.assertEqual(status, 201)
        return res["item"]["token"]

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        headers: dict[str, str] | None = None,
        token: str | None = None,
        base_url: str | None = None,
    ) -> tuple[int, dict]:
        req_headers = dict(headers or {})
        if token:
            req_headers["Authorization"] = f"Bearer {token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"{base_url or self.base_url}{path}", data=data, headers=req_headers, method=method
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

    def _table_counts(self) -> dict[str, int]:
        with db_transaction(database_url=self.pg_url) as conn:
            return {
                tbl: int(conn.execute(f"SELECT COUNT(*) AS c FROM {tbl}").fetchone()["c"])
                for tbl in self._DOMAIN_TABLES
            }

    def test_pg_migrations_apply_idempotent_rollback_and_checksum(self) -> None:
        self._stop_server()

        # 1. Roll back all applied migrations down to 0000
        rolled_all = rollback_migrations(self.pg_url, to_version="0000")
        self.assertEqual(rolled_all, ["0004", "0003", "0002", "0001"])
        status_empty = get_migration_status(self.pg_url)
        self.assertEqual(status_empty["applied"], [])
        self.assertEqual(status_empty["pending"], ["0001", "0002", "0003", "0004"])
        self.assertFalse(status_empty["current"])

        with db_transaction(database_url=self.pg_url) as conn:
            for tbl in self._DOMAIN_TABLES:
                reg = conn.execute("SELECT to_regclass(?) AS reg", (tbl,)).fetchone()["reg"]
                self.assertIsNone(reg, f"Table {tbl} should be dropped after rollback to 0000")

        # init_db with auto_migrate=False fails cleanly when migrations are pending
        with self.assertRaises(MigrationError):
            init_db(database_url=self.pg_url, auto_migrate=False)

        # 2. Apply migrations up cleanly + verify idempotent re-run
        applied = apply_migrations(self.pg_url)
        self.assertEqual(applied, ["0001", "0002", "0003", "0004"])
        applied_again = apply_migrations(self.pg_url)
        self.assertEqual(applied_again, [])
        with db_transaction(database_url=self.pg_url) as conn:
            is_curr, pending, mismatches = verify_migrations_current(conn._conn)
            self.assertTrue(is_curr)
            self.assertEqual(pending, [])
            self.assertEqual(mismatches, [])

        status_current = get_migration_status(self.pg_url)
        self.assertTrue(status_current["current"])
        self.assertEqual([a["version"] for a in status_current["applied"]], ["0001", "0002", "0003", "0004"])
        self.assertIn("://***@", status_current["target"])
        parsed_pg = urlsplit(self.pg_url)
        if parsed_pg.password:
            self.assertNotIn(parsed_pg.password, status_current["target"])
        if parsed_pg.username:
            self.assertNotIn(parsed_pg.username, status_current["target"])

        # Inspect PostgreSQL column types & RLS flags
        with db_transaction(database_url=self.pg_url) as conn:
            cols = {
                (r["table_name"], r["column_name"]): r["data_type"]
                for r in conn.execute(
                    """
                    SELECT table_name, column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                    """
                ).fetchall()
            }
            self.assertEqual(cols[("workspaces", "is_demo")], "boolean")
            self.assertEqual(cols[("workspaces", "demo_slug")], "text")
            self.assertEqual(cols[("offerings", "unit_price_idr")], "bigint")
            self.assertEqual(cols[("offerings", "requires_stock_movement")], "boolean")
            self.assertEqual(cols[("purchases", "qty")], "numeric")
            self.assertEqual(cols[("sales", "occurred_at")], "timestamp with time zone")
            self.assertEqual(cols[("inventory_pools", "qty_on_hand")], "numeric")
            self.assertEqual(cols[("inventory_pools", "total_value_idr")], "bigint")

            rls_rows = conn.execute(
                """
                SELECT relname, relrowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = current_schema() AND c.relkind = 'r'
                """
            ).fetchall()
            rls_map = {r["relname"]: bool(r["relrowsecurity"]) for r in rls_rows}
            for tbl in self._DOMAIN_TABLES + ("schema_migrations",):
                self.assertTrue(rls_map.get(tbl), f"RLS should be enabled on {tbl}")

        # 3. Checksum drift detection using a temp copy of migrations
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_migs = Path(tmpdir) / "pg"
            shutil.copytree("migrations/postgres", tmp_migs)
            target_up = tmp_migs / "0001_initial_schema.up.sql"
            target_up.write_text(target_up.read_text(encoding="utf-8") + "\n-- checksum drift\n", encoding="utf-8")
            with self.assertRaises(MigrationError):
                apply_migrations(self.pg_url, migrations_dir=tmp_migs)

        # 4. Step rollback (0002) disables RLS cleanly, then re-apply 0002
        rolled_one = rollback_migrations(self.pg_url, steps=2)
        self.assertEqual(rolled_one, ["0003", "0002"])
        with db_transaction(database_url=self.pg_url) as conn:
            rls_sales = conn.execute(
                "SELECT relrowsecurity FROM pg_class WHERE relname = 'sales'"
            ).fetchone()["relrowsecurity"]
            self.assertFalse(bool(rls_sales))
        self.assertEqual(apply_migrations(self.pg_url), ["0002", "0003"])

    def test_pg_rls_and_service_pool_privileges_and_503_unavailable(self) -> None:
        import psycopg

        anon_role = "ms_anon_test"
        svc_role = "ms_service_test"
        test_pw = "local_role_pw_only"
        domain_csv = ", ".join(self._DOMAIN_TABLES)

        with db_transaction(database_url=self.pg_url) as conn:
            for role in (anon_role, svc_role):
                exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = ?", (role,)).fetchone()
                if exists:
                    conn.execute(f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {role}")
                    conn.execute(f"REVOKE ALL PRIVILEGES ON SCHEMA public FROM {role}")
                    conn.execute(f"DROP ROLE {role}")

            conn.execute(f"CREATE ROLE {anon_role} LOGIN PASSWORD '{test_pw}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS")
            conn.execute(f"CREATE ROLE {svc_role} LOGIN PASSWORD '{test_pw}' NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS")
            conn.execute(f"GRANT USAGE ON SCHEMA public TO {anon_role}, {svc_role}")
            conn.execute(f"REVOKE ALL ON TABLE {domain_csv}, schema_migrations FROM {anon_role}")
            conn.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {domain_csv} TO {svc_role}")
            conn.execute(f"GRANT SELECT ON TABLE schema_migrations TO {svc_role}")

        anon_dsn = _replace_dsn_credentials(self.pg_url, anon_role, test_pw)
        svc_dsn = _replace_dsn_credentials(self.pg_url, svc_role, test_pw)
        svc_server = None
        svc_thread = None

        try:
            # 1. Anon role blocked from both reading and writing
            for stmt in (
                "SELECT * FROM workspaces",
                "INSERT INTO workspaces (workspace_id, name, business_type, currency, timezone, created_at) VALUES ('w', 'x', 'y', 'IDR', 'Asia/Jakarta', NOW())",
                "SELECT * FROM schema_migrations",
            ):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with db_transaction(database_url=anon_dsn) as conn:
                        conn.execute(stmt)

            # 2. Service role starts server cleanly with auto_migrate=False (no DDL required) and runs full flow
            svc_server = create_server(
                host="127.0.0.1",
                port=0,
                database_url=svc_dsn,
                auto_migrate=False,
                use_pool=True,
            )
            svc_port = svc_server.server_address[1]
            svc_thread = threading.Thread(target=svc_server.serve_forever, daemon=True)
            svc_thread.start()
            svc_base = f"http://127.0.0.1:{svc_port}"

            s_health, health_body = self._request("GET", "/health", base_url=svc_base)
            self.assertEqual(s_health, 200)
            self.assertEqual(health_body["db_backend"], "postgres")

            tok = self._login("actor_a", "dev-a-pass", base_url=svc_base)
            s_ws, ws = self._request("POST", "/v1/workspaces", {"name": "Pool WS"}, token=tok, base_url=svc_base)
            self.assertEqual(s_ws, 201)
            ws_id = ws["item"]["workspace_id"]
            s_off, off = self._request(
                "POST",
                f"/v1/workspaces/{ws_id}/offerings",
                {"name": "Beras", "offering_type": "goods", "unit_price_idr": 15000, "unit": "kg"},
                token=tok,
                base_url=svc_base,
            )
            self.assertEqual(s_off, 201)
            self.assertEqual(off["item"]["tax_status"], "not_assessed")

            # Service role cannot perform DDL or TRUNCATE
            for forbidden in ("DROP TABLE sales", "TRUNCATE TABLE sales"):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with db_transaction(database_url=svc_dsn) as conn:
                        conn.execute(forbidden)

            # 3. Connection failure maps cleanly to DomainError(503) without leaking credentials
            bad_cfg = DatabaseConfig(
                backend="postgres",
                target="postgresql://baduser:never_leak_this_pw@127.0.0.1:1/bad_db",
                connect_timeout=1,
            )
            with self.assertRaises(DomainError) as ctx_503:
                with db_transaction(bad_cfg) as conn:
                    conn.execute("SELECT 1")
            self.assertEqual(ctx_503.exception.status_code, 503)
            self.assertEqual(ctx_503.exception.code, "database_unavailable")
            self.assertNotIn("never_leak_this_pw", ctx_503.exception.message)
        finally:
            if svc_server is not None:
                svc_server.shutdown()
                svc_server.server_close()
                if svc_thread is not None:
                    svc_thread.join(timeout=2)
            with db_transaction(database_url=self.pg_url) as conn:
                for role in (anon_role, svc_role):
                    conn.execute(f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {role}")
                    conn.execute(f"REVOKE ALL PRIVILEGES ON SCHEMA public FROM {role}")
                    conn.execute(f"DROP ROLE IF EXISTS {role}")

    def test_pg_fa_warung_bakso_beras_and_fb_residual(self) -> None:
        _, ws_res = self._request("POST", "/v1/workspaces", {"name": "Warung Bakso & Beras"}, token=self.token_a)
        ws_id = ws_res["item"]["workspace_id"]
        _, off_a = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Daging & Beras Bakso", "offering_type": "goods", "unit_price_idr": 16000, "unit": "kg"},
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
        s1_code, s1 = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": off_a_id, "qty": "0.5", "total_price_idr": 8000}], "occurred_at": "2026-11-27T10:00:00+07:00"},
            headers={"Idempotency-Key": "pg-fa-s1"},
            token=self.token_a,
        )
        self.assertEqual(s1_code, 201)
        self.assertEqual(s1["item"]["total_cogs_idr"], 5500)
        self.assertEqual(s1["item"]["gross_profit_idr"], 2500)
        self.assertEqual(s1["item"]["tax_status"], "not_assessed")
        self.assertNotIn("tax_amount", s1["item"])

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

        # F-B residual: 3 units / 10.000 -> [3333, 3334, 3333], sum 10.000
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

        # Exact Decimal 0.1 + 0.2 = 0.3 NUMERIC precision
        _, off_dec = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Rempah", "offering_type": "goods", "unit_price_idr": 1000, "unit": "kg"},
            token=self.token_a,
        )
        off_dec_id = off_dec["item"]["offering_id"]
        self._request("POST", f"/v1/workspaces/{ws_id}/purchases", {"offering_id": off_dec_id, "qty": "0.1", "total_cost_idr": 100}, token=self.token_a)
        self._request("POST", f"/v1/workspaces/{ws_id}/purchases", {"offering_id": off_dec_id, "qty": "0.2", "total_cost_idr": 200}, token=self.token_a)
        with db_transaction(database_url=self.pg_url) as conn:
            pool_dec = conn.execute(
                "SELECT qty_on_hand, total_value_idr FROM inventory_pools WHERE workspace_id = ? AND offering_id = ?",
                (ws_id, off_dec_id),
            ).fetchone()
            self.assertEqual((pool_dec["qty_on_hand"], pool_dec["total_value_idr"]), ("0.3", 300))
        s_dec, _ = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": off_dec_id, "qty": "0.3", "total_price_idr": 500}]},
            token=self.token_a,
        )
        self.assertEqual(s_dec, 201)

    def test_pg_service_jasa_and_hybrid(self) -> None:
        _, ws_res = self._request("POST", "/v1/workspaces", {"name": "Jasa & Hybrid PG"}, token=self.token_a)
        ws_id = ws_res["item"]["workspace_id"]
        _, svc = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Konsultasi Jasa", "offering_type": "service", "unit_price_idr": 50000, "unit": "sesi", "tax_status": "unknown"},
            token=self.token_a,
        )
        svc_id = svc["item"]["offering_id"]
        self.assertFalse(svc["item"]["requires_stock_movement"])
        self.assertIsNone(svc["item"]["valuation_method"])
        self.assertNotIn("tax_amount", svc["item"])

        s_pur_svc, e_pur_svc = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": svc_id, "qty": "1", "total_cost_idr": 10000},
            token=self.token_a,
        )
        self.assertEqual(s_pur_svc, 422)
        self.assertEqual(e_pur_svc["code"], "service_no_stock")

        s_svc, sale_svc = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": svc_id, "qty": "1", "total_price_idr": 50000}]},
            headers={"Idempotency-Key": "pg-svc-1"},
            token=self.token_a,
        )
        self.assertEqual(s_svc, 201)
        self.assertEqual(sale_svc["item"]["cogs_status"], "open")
        self.assertIsNone(sale_svc["item"]["total_cogs_idr"])

        _, goods = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Paket Bahan", "offering_type": "goods", "unit_price_idr": 10000},
            token=self.token_a,
        )
        goods_id = goods["item"]["offering_id"]
        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": goods_id, "qty": "2", "total_cost_idr": 8000},
            token=self.token_a,
        )
        s_hyb, hyb_res = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {
                "lines": [
                    {"offering_id": goods_id, "qty": "1", "total_price_idr": 10000},
                    {"offering_id": svc_id, "qty": "1", "total_price_idr": 50000},
                ]
            },
            token=self.token_a,
        )
        self.assertEqual(s_hyb, 201)
        self.assertEqual(hyb_res["item"]["cogs_status"], "open")
        self.assertIsNone(hyb_res["item"]["total_cogs_idr"])

        _, rep = self._request("GET", f"/v1/workspaces/{ws_id}/reports/daily", token=self.token_a)
        self.assertEqual(rep["report"]["cogs_status"], "open")
        self.assertEqual(rep["report"]["gross_profit_status"], "unavailable")
        self.assertEqual(rep["report"]["ending_inventory"]["total_qty"], "1")
        self.assertEqual(rep["report"]["ending_inventory"]["total_value_idr"], 4000)

    def test_pg_two_tenant_isolation_and_membership_revocation(self) -> None:
        s_unauth, _ = self._request("GET", "/v1/workspaces")
        self.assertEqual(s_unauth, 401)

        _, ws_a = self._request(
            "POST", "/v1/workspaces", {"name": "Tenant A"}, headers={"Idempotency-Key": "pg-ws-k1"}, token=self.token_a
        )
        ws_a_id = ws_a["item"]["workspace_id"]
        _, ws_b = self._request(
            "POST", "/v1/workspaces", {"name": "Tenant B"}, headers={"Idempotency-Key": "pg-ws-k1"}, token=self.token_b
        )
        ws_b_id = ws_b["item"]["workspace_id"]
        self.assertNotEqual(ws_a_id, ws_b_id)

        _, list_a = self._request("GET", "/v1/workspaces", token=self.token_a)
        _, list_b = self._request("GET", "/v1/workspaces", token=self.token_b)
        self.assertEqual([w["workspace_id"] for w in list_a["items"]], [ws_a_id])
        self.assertEqual([w["workspace_id"] for w in list_b["items"]], [ws_b_id])

        _, off_a = self._request(
            "POST",
            f"/v1/workspaces/{ws_a_id}/offerings",
            {"name": "Produk A", "offering_type": "goods", "unit_price_idr": 10000},
            headers={"Idempotency-Key": "pg-off-a1"},
            token=self.token_a,
        )
        off_a_id = off_a["item"]["offering_id"]

        cross_routes = [
            ("GET", f"/v1/workspaces/{ws_a_id}/offerings", None),
            ("GET", f"/v1/workspaces/{ws_a_id}/offerings/{off_a_id}", None),
            ("POST", f"/v1/workspaces/{ws_a_id}/offerings", {"name": "X", "offering_type": "goods", "unit_price_idr": 1}),
            ("POST", f"/v1/workspaces/{ws_a_id}/purchases", {"offering_id": off_a_id, "qty": "1", "total_cost_idr": 100}),
            ("POST", f"/v1/workspaces/{ws_a_id}/sales", {"lines": [{"offering_id": off_a_id, "qty": "1"}]}),
            ("GET", f"/v1/workspaces/{ws_a_id}/reports/daily", None),
            ("POST", f"/v1/workspaces/{ws_a_id}/simulations", {"unit_cost_idr": 1000, "selling_price_idr": 2000}),
            ("GET", f"/v1/workspaces/{ws_a_id}/price-benchmarks/snapshots", None),
            ("POST", f"/v1/workspaces/{ws_a_id}/price-benchmarks/compare", {"source_kind": "invalid"}),
            ("GET", f"/v1/workspaces/{ws_a_id}/ai-review/config", None),
            ("POST", f"/v1/workspaces/{ws_a_id}/reports/daily/ai-review", {}),
        ]
        for method, path, body in cross_routes:
            code, err = self._request(method, path, body, token=self.token_b)
            self.assertEqual(code, 404, f"Expected 404 for actor_b on {method} {path}")
            self.assertEqual(err["code"], "workspace_not_found")

        # Cross-tenant offering reference inside actor_b's own workspace -> 404 offering_not_found
        s_cross_off, e_cross_off = self._request(
            "POST",
            f"/v1/workspaces/{ws_b_id}/purchases",
            {"offering_id": off_a_id, "qty": "1", "total_cost_idr": 100},
            token=self.token_b,
        )
        self.assertEqual(s_cross_off, 404)
        self.assertEqual(e_cross_off["code"], "offering_not_found")

        # Revoke actor_a membership -> workspace replay returns 403 and workspace routes return 404
        BaselineService(database_url=self.pg_url).revoke_membership(ws_a_id, "actor_a")
        s_rep_rev, _ = self._request(
            "POST",
            "/v1/workspaces",
            {"name": "Tenant A"},
            headers={"Idempotency-Key": "pg-ws-k1"},
            token=self.token_a,
        )
        self.assertEqual(s_rep_rev, 403)
        s_off_rev, _ = self._request("GET", f"/v1/workspaces/{ws_a_id}/offerings", token=self.token_a)
        self.assertEqual(s_off_rev, 404)

    def test_pg_concurrency_idempotency_and_atomic_rollback(self) -> None:
        _, ws_res = self._request("POST", "/v1/workspaces", {"name": "Atomic PG"}, token=self.token_a)
        ws_id = ws_res["item"]["workspace_id"]
        _, off = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Stok Ketat", "offering_type": "goods", "unit_price_idr": 10000},
            token=self.token_a,
        )
        off_id = off["item"]["offering_id"]
        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_id, "qty": "2", "total_cost_idr": 8000},
            token=self.token_a,
        )

        # Sequential idempotency replay & conflict
        c1, b1 = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": off_id, "qty": "0.5", "total_price_idr": 5000}]},
            headers={"Idempotency-Key": "seq-1"},
            token=self.token_a,
        )
        c2, b2 = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": off_id, "qty": "0.5", "total_price_idr": 5000}]},
            headers={"Idempotency-Key": "seq-1"},
            token=self.token_a,
        )
        self.assertEqual((c1, c2), (201, 201))
        self.assertEqual(b1["item"]["sale_id"], b2["item"]["sale_id"])

        c_conf, e_conf = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": off_id, "qty": "1", "total_price_idr": 10000}]},
            headers={"Idempotency-Key": "seq-1"},
            token=self.token_a,
        )
        self.assertEqual(c_conf, 409)
        self.assertEqual(e_conf["code"], "idempotency_conflict")

        # Concurrent identical idempotency key -> single sale created, both receive 201 with same sale_id
        same_res: list[tuple[int, str]] = []
        lock = threading.Lock()

        def same_call() -> None:
            c, b = self._request(
                "POST",
                f"/v1/workspaces/{ws_id}/sales",
                {"lines": [{"offering_id": off_id, "qty": "0.5", "total_price_idr": 5000}]},
                headers={"Idempotency-Key": "pg-conc-1"},
                token=self.token_a,
            )
            with lock:
                same_res.append((c, b.get("item", {}).get("sale_id", "")))

        t1, t2 = threading.Thread(target=same_call), threading.Thread(target=same_call)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        self.assertEqual([r[0] for r in same_res], [201, 201])
        self.assertEqual(same_res[0][1], same_res[1][1])

        # Concurrent last-unit race (1.0 remaining) -> one 201, one 409 insufficient_stock
        race_codes: list[int] = []

        def race_call(idx: int) -> None:
            c, _ = self._request(
                "POST",
                f"/v1/workspaces/{ws_id}/sales",
                {"lines": [{"offering_id": off_id, "qty": "1", "total_price_idr": 10000}]},
                headers={"Idempotency-Key": f"pg-race-{idx}"},
                token=self.token_a,
            )
            with lock:
                race_codes.append(c)

        t3, t4 = threading.Thread(target=race_call, args=(1,)), threading.Thread(target=race_call, args=(2,))
        t3.start()
        t4.start()
        t3.join()
        t4.join()
        self.assertEqual(sorted(race_codes), [201, 409])

        # Atomic transaction rollback via fault injection at both stages
        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": off_id, "qty": "2", "total_cost_idr": 8000},
            token=self.token_a,
        )
        before_counts = self._table_counts()
        svc = BaselineService(database_url=self.pg_url)

        def boom(_conn: object) -> None:
            raise RuntimeError("Injected PG crash")

        for stage in ("stock_movements", "pre_commit"):
            with self.assertRaises(RuntimeError):
                svc.create_sale(
                    ws_id,
                    "actor_a",
                    {"lines": [{"offering_id": off_id, "qty": "1", "total_price_idr": 10000}]},
                    idempotency_key=f"pg-fault-{stage}",
                    actor="actor_a",
                    fault_injector=boom,
                    fault_stage=stage,
                )

        self.assertEqual(self._table_counts(), before_counts)
        with db_transaction(database_url=self.pg_url) as conn:
            pool_row = conn.execute(
                "SELECT qty_on_hand, total_value_idr FROM inventory_pools WHERE workspace_id = ? AND offering_id = ?",
                (ws_id, off_id),
            ).fetchone()
            batch_sum = conn.execute(
                "SELECT SUM(qty_remaining) AS rem FROM inventory_batches WHERE workspace_id = ? AND offering_id = ?",
                (ws_id, off_id),
            ).fetchone()["rem"]
            self.assertEqual((pool_row["qty_on_hand"], pool_row["total_value_idr"]), ("2", 8000))
            self.assertEqual(Decimal(batch_sum), Decimal("2"))

    def test_pg_decimal_boundaries_wib_cutoff_audit_and_readonly(self) -> None:
        _, ws_res = self._request(
            "POST", "/v1/workspaces", {"name": "Boundary & Cutoff PG", "timezone": "Asia/Jakarta"}, token=self.token_a
        )
        ws_id = ws_res["item"]["workspace_id"]

        # Valid 10^15 BIGINT price boundary & overflow guard
        s_off_max, d_off_max = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Jasa Skala Besar", "offering_type": "service", "unit_price_idr": 10**15, "unit": "paket"},
            token=self.token_a,
        )
        self.assertEqual(s_off_max, 201)
        s_ov, d_ov = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": d_off_max["item"]["offering_id"], "qty": "10000"}]},
            token=self.token_a,
        )
        self.assertEqual(s_ov, 422)
        self.assertEqual(d_ov["code"], "value_overflow")

        # Micro qty 1e-16 preserved in PostgreSQL NUMERIC + simulation overflow 422
        _, off_micro = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Barang Mikro", "offering_type": "goods", "unit_price_idr": 1000},
            token=self.token_a,
        )
        micro_id = off_micro["item"]["offering_id"]
        s_pm, _ = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": micro_id, "qty": "0.0000000000000001", "total_cost_idr": 10**15},
            token=self.token_a,
        )
        self.assertEqual(s_pm, 201)
        s_sim_ov, d_sim_ov = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/simulations",
            {"offering_id": micro_id},
            token=self.token_a,
        )
        self.assertEqual(s_sim_ov, 422)
        self.assertEqual(d_sim_ov["code"], "value_overflow")

        # WIB (Asia/Jakarta) midnight cutoff: 23:59:59+07:00 vs 00:00:00+07:00
        _, off_wib = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/offerings",
            {"name": "Beras Cutoff", "offering_type": "goods", "unit_price_idr": 15000, "unit": "kg"},
            token=self.token_a,
        )
        wib_id = off_wib["item"]["offering_id"]
        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": wib_id, "qty": "10", "total_cost_idr": 100000, "occurred_at": "2026-11-26T23:59:58+07:00"},
            token=self.token_a,
        )
        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": wib_id, "qty": "2", "total_price_idr": 30000}], "occurred_at": "2026-11-26T23:59:59+07:00"},
            token=self.token_a,
        )
        self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/sales",
            {"lines": [{"offering_id": wib_id, "qty": "3", "total_price_idr": 45000}], "occurred_at": "2026-11-27T00:00:00+07:00"},
            token=self.token_a,
        )
        # Out-of-order purchase timestamp rejected
        s_ooo, e_ooo = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/purchases",
            {"offering_id": wib_id, "qty": "1", "total_cost_idr": 10000, "occurred_at": "2026-11-26T23:00:00+07:00"},
            token=self.token_a,
        )
        self.assertEqual(s_ooo, 422)
        self.assertEqual(e_ooo["code"], "out_of_order_timestamp")

        _, rep_d1 = self._request("GET", f"/v1/workspaces/{ws_id}/reports/daily?date=2026-11-26", token=self.token_a)
        _, rep_d2 = self._request("GET", f"/v1/workspaces/{ws_id}/reports/daily?date=2026-11-27", token=self.token_a)
        self.assertEqual(rep_d1["report"]["revenue_idr"], 30000)
        self.assertEqual(rep_d1["report"]["cogs_idr"], 20000)
        self.assertEqual(rep_d1["report"]["cash_in_idr"], 30000)
        self.assertEqual(rep_d1["report"]["cash_out_idr"], 100000)
        d1_wib_inv = next(i for i in rep_d1["report"]["ending_inventory"]["items"] if i["offering_id"] == wib_id)
        self.assertEqual((d1_wib_inv["qty_remaining"], d1_wib_inv["value_idr"]), ("8", 80000))

        self.assertEqual(rep_d2["report"]["revenue_idr"], 45000)
        self.assertEqual(rep_d2["report"]["cogs_idr"], 30000)
        d2_wib_inv = next(i for i in rep_d2["report"]["ending_inventory"]["items"] if i["offering_id"] == wib_id)
        self.assertEqual((d2_wib_inv["qty_remaining"], d2_wib_inv["value_idr"]), ("5", 50000))

        # Audit trail parity
        with db_transaction(database_url=self.pg_url) as conn:
            actions = [
                r["action"]
                for r in conn.execute(
                    "SELECT action FROM audit_events WHERE workspace_id = ? ORDER BY created_at ASC",
                    (ws_id,),
                ).fetchall()
            ]
        for expected in ("workspace.created", "offering.created", "purchase.created", "sale.created"):
            self.assertIn(expected, actions)

        # Read-only endpoints never mutate ledger tables
        counts_before = self._table_counts()
        s_sim, d_sim = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/simulations",
            {"offering_id": wib_id, "discount_percent": "10"},
            token=self.token_a,
        )
        self.assertEqual(s_sim, 200)
        self.assertEqual(d_sim["item"]["net_price_idr"], 13500)
        s_bench, d_bench = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/price-benchmarks/compare",
            {"offering_id": wib_id, "source_kind": "transcribed_official", "snapshot_id": "bapanas_beras_medium_maret_2026"},
            token=self.token_a,
        )
        self.assertEqual(s_bench, 200)
        self.assertEqual(d_bench["item"]["normalized_benchmark_price_idr"], 13378)
        s_ai, d_ai = self._request(
            "POST",
            f"/v1/workspaces/{ws_id}/reports/daily/ai-review",
            {"date": "2026-11-27", "stub_mode": "stub_valid"},
            token=self.token_a,
        )
        self.assertEqual(s_ai, 200)
        self.assertTrue(d_ai["item"]["ledger_unchanged"])
        self.assertEqual(self._table_counts(), counts_before)

    def test_pg_demo_workspace_bootstrap_replay_and_enriched_drilldown(self) -> None:
        s1, d1 = self._request("POST", "/v1/workspaces/demo", {}, token=self.token_a)
        self.assertEqual(s1, 201)
        item1 = d1["item"]
        self.assertTrue(item1["created"])
        self.assertFalse(item1["idempotent_replay"])
        self.assertEqual(item1["scenario_slug"], "warung_bakso_sembako_v1")
        ws_a_demo = item1["workspace"]
        ws_id = ws_a_demo["workspace_id"]
        self.assertTrue(ws_a_demo["is_demo"])
        self.assertEqual(ws_a_demo["demo_slug"], "warung_bakso_sembako_v1")

        # Idempotent replay for actor_a returns 200 and same workspace
        s2, d2 = self._request("POST", "/v1/workspaces/demo", {}, token=self.token_a)
        self.assertEqual(s2, 200)
        self.assertFalse(d2["item"]["created"])
        self.assertTrue(d2["item"]["idempotent_replay"])
        self.assertEqual(d2["item"]["workspace"]["workspace_id"], ws_id)

        # Actor B receives an isolated demo workspace and gets 404 accessing Actor A's demo workspace
        sb_demo, db_demo = self._request("POST", "/v1/workspaces/demo", {}, token=self.token_b)
        self.assertEqual(sb_demo, 201)
        self.assertNotEqual(db_demo["item"]["workspace"]["workspace_id"], ws_id)
        s_cross, e_cross = self._request("GET", f"/v1/workspaces/{ws_id}/offerings", token=self.token_b)
        self.assertEqual(s_cross, 404)
        self.assertEqual(e_cross["code"], "workspace_not_found")

        # Offerings include joined inventory_pools metrics on PostgreSQL
        s_offs, d_offs = self._request("GET", f"/v1/workspaces/{ws_id}/offerings", token=self.token_a)
        self.assertEqual(s_offs, 200)
        by_name = {o["name"]: o for o in d_offs["items"]}
        self.assertEqual(by_name["Bakso Urat"]["qty_on_hand"], "6")
        self.assertEqual(by_name["Bakso Urat"]["inventory_value_idr"], 54000)
        self.assertEqual(by_name["Bakso Urat"]["wa_unit_cost_idr"], 9000)
        self.assertEqual(by_name["Beras Medium"]["qty_on_hand"], "10")
        self.assertEqual(by_name["Beras Medium"]["inventory_value_idr"], 120000)
        self.assertEqual(by_name["Beras Medium"]["wa_unit_cost_idr"], 12000)
        self.assertIsNone(by_name["Jasa Katering Acara"]["qty_on_hand"])
        self.assertIsNone(by_name["Jasa Katering Acara"]["inventory_value_idr"])
        self.assertIsNone(by_name["Jasa Katering Acara"]["wa_unit_cost_idr"])

        # Daily report oracle figures & enriched drill-down (offering_name, unit, sale lines)
        demo_date = item1["demo_date"]
        s_rep, d_rep = self._request(
            "GET", f"/v1/workspaces/{ws_id}/reports/daily?date={demo_date}", token=self.token_a
        )
        self.assertEqual(s_rep, 200)
        rep = d_rep["report"]
        self.assertEqual(rep["revenue_idr"], 60000)
        self.assertEqual(rep["cogs_idr"], 36000)
        self.assertEqual(rep["gross_profit_idr"], 24000)
        self.assertEqual(rep["net_cash_flow_idr"], -150000)
        self.assertEqual(rep["ending_inventory"]["total_value_idr"], 174000)
        self.assertEqual(rep["drill_down"]["purchases"][0]["offering_name"], "Bakso Urat")
        self.assertEqual(rep["drill_down"]["sales"][0]["lines"][0]["offering_name"], "Bakso Urat")
        self.assertEqual(rep["drill_down"]["stock_movements"][0]["offering_name"], "Bakso Urat")

        # Cross-midnight determinism on PostgreSQL TIMESTAMPTZ
        past_utc = "2026-11-25T03:00:00+00:00"
        with db_transaction(database_url=self.pg_url) as conn:
            conn.execute("UPDATE workspaces SET created_at = ? WHERE workspace_id = ?", (past_utc, ws_id))
            conn.execute("UPDATE purchases SET occurred_at = ? WHERE workspace_id = ?", (past_utc, ws_id))
            conn.execute("UPDATE sales SET occurred_at = ? WHERE workspace_id = ?", (past_utc, ws_id))
            conn.execute("UPDATE stock_movements SET occurred_at = ? WHERE workspace_id = ?", (past_utc, ws_id))
            conn.execute("UPDATE cash_movements SET occurred_at = ? WHERE workspace_id = ?", (past_utc, ws_id))

        s3, d3 = self._request("POST", "/v1/workspaces/demo", {}, token=self.token_a)
        self.assertEqual(s3, 200)
        self.assertTrue(d3["item"]["idempotent_replay"])
        self.assertEqual(d3["item"]["demo_date"], "2026-11-25")
        s_past_rep, d_past_rep = self._request(
            "GET", f"/v1/workspaces/{ws_id}/reports/daily?date=2026-11-25", token=self.token_a
        )
        self.assertEqual(s_past_rep, 200)
        self.assertEqual(d_past_rep["report"]["net_cash_flow_idr"], -150000)
        self.assertEqual(d_past_rep["report"]["ending_inventory"]["total_value_idr"], 174000)


if __name__ == "__main__":
    unittest.main()
