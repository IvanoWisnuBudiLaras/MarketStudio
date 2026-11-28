"""Automated tests for MarketStudio backup and restore tool (Issue #44)."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app.db import init_db
from app.service import BaselineService
from scripts.backup_restore import (
    BackupCorruptError,
    BackupMetadata,
    BackupRestoreError,
    ChecksumMismatchError,
    RestoreResult,
    SourceDatabaseNotFoundError,
    TargetPathInvalidError,
    VerificationFailedError,
    backup_database,
    backup_postgres,
    backup_sqlite,
    check_sqlite_integrity,
    compute_sha256,
    get_sqlite_table_counts,
    restore_database,
    restore_postgres,
    restore_sqlite,
    run_synthetic_drill,
    verify_all,
    verify_business_reports,
    verify_operational_health,
    verify_quantitative_tables,
    verify_security_isolation,
)


class BackupRestoreCoreTest(unittest.TestCase):
    """Core functionality tests for SQLite backup, restore, and multi-tier verifications."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tmpdir.name)
        self.source_db = self.base_dir / "test_source.db"
        self.backup_file = self.base_dir / "test_backup.db"
        self.meta_file = self.base_dir / "test_backup.json"
        self.restored_db = self.base_dir / "test_restored.db"

        # Initialize source database with synthetic fixtures
        init_db(str(self.source_db))
        self.service = BaselineService(str(self.source_db))

        # Primary Tenant (Warung Bakso & Sembako with financial movements)
        self.owner_actor = "usr_demo_owner"
        _, seed_info = self.service.bootstrap_demo_workspace(self.owner_actor)
        self.ws_id = seed_info["workspace"]["workspace_id"]
        self.demo_date = seed_info["demo_date"]

        # Add revoked member for security revocation preservation verification
        with closing(sqlite3.connect(str(self.source_db))) as conn:
            conn.execute(
                """
                INSERT INTO workspace_memberships (workspace_id, actor_id, role, created_at, revoked_at)
                VALUES (?, 'usr_revoked_staff', 'staff', '2026-11-28T08:00:00Z', '2026-11-28T09:00:00Z')
                """,
                (self.ws_id,),
            )
            conn.commit()

        # Secondary Tenant (Isolated)
        _, res2 = self.service.create_workspace(
            {"name": "Toko Retail Terpisah", "business_type": "umkm_hybrid"},
            actor="usr_tenant_2",
        )
        self.ws2_id = res2["workspace_id"]
        self.service.create_offering(
            workspace_id=self.ws2_id,
            actor_id="usr_tenant_2",
            payload={
                "name": "Barang Sekunder",
                "offering_type": "goods",
                "unit_price_idr": 25000,
                "unit": "pcs",
            },
            actor="usr_tenant_2",
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_sqlite_backup_and_restore_cycle(self) -> None:
        # 1. Backup
        meta = backup_sqlite(self.source_db, self.backup_file, metadata_path=self.meta_file)
        self.assertIsInstance(meta, BackupMetadata)
        self.assertEqual(meta.backend, "sqlite")
        self.assertTrue(self.backup_file.is_file())
        self.assertGreater(meta.artifact_size_bytes, 0)
        self.assertEqual(len(meta.sha256), 64)
        self.assertGreater(meta.duration_ms, 0)
        self.assertGreater(len(meta.tables_count), 0)

        # Metadata sidecar verification
        self.assertTrue(self.meta_file.is_file())
        sidecar_data = json.loads(self.meta_file.read_text(encoding="utf-8"))
        self.assertEqual(sidecar_data["sha256"], meta.sha256)
        self.assertEqual(sidecar_data["artifact_size_bytes"], meta.artifact_size_bytes)

        # 2. Restore
        restore_res = restore_sqlite(
            self.backup_file,
            self.restored_db,
            expected_checksum=meta.sha256,
            verify_integrity=True,
        )
        self.assertIsInstance(restore_res, RestoreResult)
        self.assertEqual(restore_res.backend, "sqlite")
        self.assertTrue(self.restored_db.is_file())
        self.assertTrue(restore_res.sha256_verified)
        self.assertEqual(restore_res.integrity_status, "ok")
        self.assertEqual(restore_res.sha256, meta.sha256)

        # 3. Quantitative row count verification
        quant = verify_quantitative_tables(self.source_db, self.restored_db)
        self.assertEqual(quant["status"], "passed")
        self.assertEqual(quant["total_rows_source"], quant["total_rows_restored"])
        self.assertEqual(quant["tables_checked"], 17)
        for t_name, counts in quant["tables"].items():
            self.assertEqual(counts["source"], counts["restored"], f"Mismatch on table {t_name}")

        # 4. Business report verification (cash flow, gross profit, cogs, stock balance)
        biz = verify_business_reports(self.source_db, self.restored_db, workspace_id=self.ws_id)
        self.assertEqual(biz["status"], "passed")
        self.assertEqual(biz["workspaces_verified"], 1)
        rep = biz["reports"][0]
        self.assertEqual(rep["revenue_idr"], 60000)
        self.assertEqual(rep["cogs_idr"], 36000)
        self.assertEqual(rep["gross_profit_idr"], 24000)
        self.assertEqual(rep["cash_in_idr"], 60000)
        self.assertEqual(rep["cash_out_idr"], 210000)
        self.assertEqual(rep["net_cash_flow_idr"], -150000)
        self.assertEqual(rep["inventory_total_value_idr"], 174000)
        self.assertEqual(rep["inventory_items_count"], 2)

        # 5. Security isolation verification
        sec = verify_security_isolation(self.restored_db, workspace_id=self.ws_id)
        self.assertEqual(sec["status"], "passed")
        self.assertTrue(sec["foreign_actor_rejected"])
        self.assertTrue(sec["unauthenticated_rejected"])
        self.assertTrue(sec["revoked_member_rejected"])

        # 6. Operational /health verification
        health = verify_operational_health(self.restored_db)
        self.assertEqual(health["status"], "passed")
        self.assertEqual(health["http_status"], 200)
        self.assertEqual(health["payload"]["status"], "ok")
        self.assertEqual(health["payload"]["db_backend"], "sqlite")

        # 7. Combined verify_all call
        full_ver = verify_all(self.source_db, self.restored_db, workspace_id=self.ws_id, check_health=True)
        self.assertEqual(full_ver["status"], "passed")
        self.assertEqual(full_ver["quantitative"]["status"], "passed")
        self.assertEqual(full_ver["business_reports"]["status"], "passed")
        self.assertEqual(full_ver["security_isolation"]["status"], "passed")
        self.assertEqual(full_ver["operational_health"]["status"], "passed")

    def test_run_synthetic_drill_library(self) -> None:
        drill_res = run_synthetic_drill(work_dir=self.base_dir / "drill_run", clean_up=False)
        self.assertEqual(drill_res["status"], "passed")
        self.assertIn("backup", drill_res)
        self.assertIn("restore", drill_res)
        self.assertIn("verification", drill_res)
        self.assertEqual(drill_res["verification"]["quantitative"]["status"], "passed")
        self.assertEqual(drill_res["verification"]["business_reports"]["status"], "passed")
        self.assertEqual(drill_res["verification"]["security_isolation"]["status"], "passed")
        self.assertEqual(drill_res["verification"]["operational_health"]["status"], "passed")


class BackupRestoreFailureScenariosTest(unittest.TestCase):
    """Test robustness against corrupt backups, checksum mismatches, and invalid target paths."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tmpdir.name)
        self.source_db = self.base_dir / "source.db"
        self.backup_file = self.base_dir / "valid_backup.db"
        self.target_db = self.base_dir / "target.db"

        init_db(str(self.source_db))
        service = BaselineService(str(self.source_db))
        service.bootstrap_demo_workspace("usr_owner")
        self.meta = backup_sqlite(self.source_db, self.backup_file)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_checksum_mismatch_fails_restore_without_modifying_target(self) -> None:
        wrong_checksum = "0" * 64
        with self.assertRaises(ChecksumMismatchError) as ctx:
            restore_sqlite(self.backup_file, self.target_db, expected_checksum=wrong_checksum)
        self.assertIn("Checksum SHA-256 tidak cocok", str(ctx.exception))
        self.assertFalse(self.target_db.exists(), "Target database should not be created on checksum failure")

    def test_corrupt_truncated_backup_file_detected(self) -> None:
        # Create truncated file (only 50 bytes)
        truncated_file = self.base_dir / "truncated.backup"
        truncated_file.write_bytes(b"SQLite format 3\x00truncated content shorter than 100")

        with self.assertRaises(BackupCorruptError) as ctx:
            restore_sqlite(truncated_file, self.target_db)
        self.assertIn("terpotong atau kosong", str(ctx.exception))

    def test_corrupt_magic_header_detected(self) -> None:
        bad_header_file = self.base_dir / "bad_header.backup"
        bad_header_file.write_bytes(b"NOT_A_SQLITE_MAGIC_HEADER_GARBAGE_PAYLOAD_" * 5)

        with self.assertRaises(BackupCorruptError) as ctx:
            restore_sqlite(bad_header_file, self.target_db)
        self.assertIn("Header SQLite tidak valid", str(ctx.exception))

    def test_corrupt_database_pages_detected(self) -> None:
        corrupted_file = self.base_dir / "corrupted_pages.backup"
        raw_bytes = bytearray(self.backup_file.read_bytes())
        # Corrupt b-tree page structure and cell pointers in database page
        raw_bytes[100] = 0xAA
        raw_bytes[103] = 0xFF
        raw_bytes[104] = 0xFF
        corrupted_file.write_bytes(raw_bytes)

        with self.assertRaises(BackupCorruptError) as ctx:
            restore_sqlite(corrupted_file, self.target_db, verify_integrity=True)
        self.assertTrue(
            "tidak lolos uji integritas" in str(ctx.exception)
            or "PRAGMA integrity_check gagal" in str(ctx.exception)
            or "malformed" in str(ctx.exception)
            or "tidak valid atau korup" in str(ctx.exception)
        )

    def test_target_path_is_existing_directory_raises_error(self) -> None:
        dir_target = self.base_dir / "existing_dir"
        dir_target.mkdir(parents=True, exist_ok=True)

        with self.assertRaises(TargetPathInvalidError) as ctx:
            restore_sqlite(self.backup_file, dir_target)
        self.assertIn("merupakan direktori", str(ctx.exception))

    def test_source_database_not_found_raises_error(self) -> None:
        non_existent_source = self.base_dir / "does_not_exist.db"
        with self.assertRaises(SourceDatabaseNotFoundError) as ctx:
            backup_sqlite(non_existent_source, self.base_dir / "fail.backup")
        self.assertIn("tidak ditemukan", str(ctx.exception))

    def test_quantitative_row_count_mismatch_detected(self) -> None:
        restore_sqlite(self.backup_file, self.target_db)
        # Artificially modify restored database table counts
        with closing(sqlite3.connect(str(self.target_db))) as conn:
            conn.execute("DELETE FROM offerings WHERE offering_id = (SELECT offering_id FROM offerings LIMIT 1)")
            conn.commit()

        with self.assertRaises(VerificationFailedError) as ctx:
            verify_quantitative_tables(self.source_db, self.target_db)
        self.assertIn("Verifikasi kuantitatif gagal", str(ctx.exception))

    def test_financial_report_mismatch_detected(self) -> None:
        restore_sqlite(self.backup_file, self.target_db)
        # Artificially tamper with revenue in sales table
        with closing(sqlite3.connect(str(self.target_db))) as conn:
            conn.execute("UPDATE sales SET total_revenue_idr = total_revenue_idr + 999999")
            conn.commit()

        with self.assertRaises(VerificationFailedError) as ctx:
            verify_business_reports(self.source_db, self.target_db)
        self.assertIn("Verifikasi laporan keuangan", str(ctx.exception))

    def test_missing_workspace_in_restored_db_fails_report_verification(self) -> None:
        restore_sqlite(self.backup_file, self.target_db)
        with closing(sqlite3.connect(str(self.target_db))) as conn:
            conn.execute("DELETE FROM workspaces")
            conn.commit()

        with self.assertRaises(VerificationFailedError) as ctx:
            verify_business_reports(self.source_db, self.target_db)
        self.assertIn("Tidak ditemukan workspace", str(ctx.exception))


class BackupRestoreCLITest(unittest.TestCase):
    """End-to-end tests for the backup_restore.py command line interface."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tmpdir.name)
        self.script_path = str(Path(__file__).resolve().parents[1] / "scripts" / "backup_restore.py")
        self.source_db = self.base_dir / "cli_source.db"
        self.backup_file = self.base_dir / "cli_backup.db"
        self.meta_file = self.base_dir / "cli_backup.json"
        self.restored_db = self.base_dir / "cli_restored.db"

        # Populate synthetic source
        init_db(str(self.source_db))
        service = BaselineService(str(self.source_db))
        service.bootstrap_demo_workspace("usr_cli_owner")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_cli_backup_and_restore_and_verify(self) -> None:
        # 1. CLI backup with --json
        cmd_backup = [
            sys.executable,
            self.script_path,
            "backup",
            "--source",
            str(self.source_db),
            "--output",
            str(self.backup_file),
            "--metadata",
            str(self.meta_file),
            "--json",
        ]
        proc_b = subprocess.run(cmd_backup, capture_output=True, text=True, check=False)
        self.assertEqual(proc_b.returncode, 0, f"STDOUT: {proc_b.stdout}\nSTDERR: {proc_b.stderr}")
        meta_json = json.loads(proc_b.stdout)
        self.assertEqual(meta_json["backend"], "sqlite")
        checksum = meta_json["sha256"]
        self.assertTrue(self.backup_file.is_file())
        self.assertTrue(self.meta_file.is_file())

        # 2. CLI restore with --checksum and text mode
        cmd_restore = [
            sys.executable,
            self.script_path,
            "restore",
            "--backup-file",
            str(self.backup_file),
            "--target",
            str(self.restored_db),
            "--checksum",
            checksum,
        ]
        proc_r = subprocess.run(cmd_restore, capture_output=True, text=True, check=False)
        self.assertEqual(proc_r.returncode, 0, f"STDOUT: {proc_r.stdout}\nSTDERR: {proc_r.stderr}")
        self.assertIn("[PASS] Basis data berhasil dipulihkan", proc_r.stdout)
        self.assertIn("verified", proc_r.stdout)
        self.assertTrue(self.restored_db.is_file())

        # 3. CLI verify command
        cmd_verify = [
            sys.executable,
            self.script_path,
            "verify",
            "--source-db",
            str(self.source_db),
            "--restored-db",
            str(self.restored_db),
        ]
        proc_v = subprocess.run(cmd_verify, capture_output=True, text=True, check=False)
        self.assertEqual(proc_v.returncode, 0, f"STDOUT: {proc_v.stdout}\nSTDERR: {proc_v.stderr}")
        self.assertIn("[PASS] Seluruh verifikasi integritas berhasil", proc_v.stdout)
        self.assertIn("17", proc_v.stdout)

    def test_cli_drill_command_json_and_text(self) -> None:
        # JSON mode
        cmd_drill_json = [
            sys.executable,
            self.script_path,
            "drill",
            "--json",
        ]
        proc_json = subprocess.run(cmd_drill_json, capture_output=True, text=True, check=False)
        self.assertEqual(proc_json.returncode, 0, f"STDOUT: {proc_json.stdout}\nSTDERR: {proc_json.stderr}")
        res_data = json.loads(proc_json.stdout)
        self.assertEqual(res_data["status"], "passed")
        self.assertIn("backup", res_data)
        self.assertIn("restore", res_data)
        self.assertIn("verification", res_data)

        # Text mode
        cmd_drill_txt = [
            sys.executable,
            self.script_path,
            "drill",
        ]
        proc_txt = subprocess.run(cmd_drill_txt, capture_output=True, text=True, check=False)
        self.assertEqual(proc_txt.returncode, 0, f"STDOUT: {proc_txt.stdout}\nSTDERR: {proc_txt.stderr}")
        self.assertIn("[PASS] Synthetic Backup & Restore Drill Berhasil 100%:", proc_txt.stdout)
        self.assertIn("MATCH", proc_txt.stdout)

    def test_cli_exit_codes(self) -> None:
        # Exit code 2: missing subcommand or invalid args
        proc_no_args = subprocess.run([sys.executable, self.script_path], capture_output=True, text=True, check=False)
        self.assertEqual(proc_no_args.returncode, 2)

        # Exit code 2: source database not found
        proc_missing_src = subprocess.run(
            [sys.executable, self.script_path, "backup", "-s", "/non/existent/db.db", "-o", "/tmp/out.db"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc_missing_src.returncode, 2)
        self.assertIn("ERROR", proc_missing_src.stderr)

        # Exit code 1: checksum mismatch on restore
        proc_bad_csum = subprocess.run(
            [
                sys.executable,
                self.script_path,
                "restore",
                "-b",
                str(self.source_db),
                "-t",
                str(self.restored_db),
                "-c",
                "wrongchecksum" * 4,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc_bad_csum.returncode, 1)
        self.assertIn("Checksum SHA-256 tidak cocok", proc_bad_csum.stderr)


class PostgresBackupRestoreSupportTest(unittest.TestCase):
    """Test PostgreSQL backup/restore tool validation and graceful degradation."""

    def test_postgres_tools_missing_raises_informative_error(self) -> None:
        with patch("shutil.which", return_value=None):
            with self.assertRaises(BackupRestoreError) as ctx_b:
                backup_postgres("postgres://localhost/test", "/tmp/pg.dump")
            self.assertIn("pg_dump", str(ctx_b.exception))

            with self.assertRaises(BackupRestoreError) as ctx_r:
                restore_postgres("/tmp/pg.dump", "postgres://localhost/test")
            self.assertIn("pg_restore", str(ctx_r.exception))

    def test_postgres_backup_fails_gracefully_on_unreachable_server(self) -> None:
        if not shutil.which("pg_dump"):
            self.skipTest("pg_dump executable not available on host")

        # Port 59999 is intentionally unreachable
        dummy_dsn = "postgresql://invalid_user:invalid_pass@127.0.0.1:59999/invalid_db?connect_timeout=1"
        with tempfile.TemporaryDirectory() as tmp:
            dump_file = Path(tmp) / "dummy.dump"
            with self.assertRaises(BackupRestoreError) as ctx:
                backup_postgres(dummy_dsn, dump_file)
            self.assertIn("pg_dump gagal", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
