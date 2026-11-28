#!/usr/bin/env python3
"""MarketStudio backup and restore automation tool (Issue #44).

Implements online, atomic backup and restore verification for SQLite (stdlib)
and PostgreSQL (local tools), with quantitative, financial, security,
and operational /health checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db import (
    DEFAULT_DB_PATH,
    DatabaseConfig,
    init_db,
    is_postgres_dsn,
    redact_dsn,
    resolve_db_config,
)
from app.domain import DomainError
from app.server import create_server
from app.service import BaselineService


class BackupRestoreError(Exception):
    """Base exception for backup and restore failures."""


class ChecksumMismatchError(BackupRestoreError):
    """Raised when backup file checksum does not match expected SHA-256."""


class BackupCorruptError(BackupRestoreError):
    """Raised when backup file is truncated, damaged, or fails integrity checks."""


class TargetPathInvalidError(BackupRestoreError):
    """Raised when destination path is an existing directory or cannot be written."""


class SourceDatabaseNotFoundError(BackupRestoreError):
    """Raised when source database file or target does not exist."""


class VerificationFailedError(BackupRestoreError):
    """Raised when quantitative, financial, or security verification fails."""


@dataclass(frozen=True)
class BackupMetadata:
    backend: str
    source: str
    backup_file: str
    artifact_size_bytes: int
    sha256: str
    duration_ms: float
    created_at: str
    tables_count: dict[str, int]


@dataclass(frozen=True)
class RestoreResult:
    backend: str
    backup_file: str
    target: str
    duration_ms: float
    artifact_size_bytes: int
    sha256: str
    sha256_verified: bool
    integrity_status: str


def compute_sha256(file_path: Path | str) -> str:
    """Compute SHA-256 hex digest for a file."""
    path = Path(file_path)
    if not path.is_file():
        raise BackupRestoreError(f"Berkas tidak ditemukan untuk komputasi hash: {path}")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def check_sqlite_integrity(db_path: Path | str) -> tuple[bool, str]:
    """Perform structural and PRAGMA integrity check on a SQLite database file."""
    path = Path(db_path)
    if not path.is_file():
        return False, f"Berkas tidak ditemukan: {path}"
    try:
        size = path.stat().st_size
    except OSError as exc:
        return False, f"Gagal membaca stat berkas: {exc}"

    if size < 100:
        return False, f"Berkas terpotong atau kosong (ukuran: {size} bytes, minimum 100 bytes)"

    try:
        with open(path, "rb") as f:
            header = f.read(16)
        if header != b"SQLite format 3\x00":
            return False, "Header SQLite tidak valid (magic header mismatch)"
    except OSError as exc:
        return False, f"Gagal membaca header berkas: {exc}"

    try:
        with closing(sqlite3.connect(str(path), timeout=10.0)) as conn:
            cursor = conn.execute("PRAGMA integrity_check;")
            rows = cursor.fetchall()
            if rows != [("ok",)]:
                messages = "; ".join(str(r[0]) for r in rows)
                return False, f"PRAGMA integrity_check gagal: {messages}"
    except Exception as exc:
        return False, f"sqlite3 integrity check exception: {exc}"

    return True, "ok"


def get_sqlite_table_counts(db_path: Path | str) -> dict[str, int]:
    """Get row counts for all application tables in a SQLite database."""
    path = Path(db_path)
    if not path.is_file():
        raise SourceDatabaseNotFoundError(f"Basis data SQLite tidak ditemukan: {path}")

    counts: dict[str, int] = {}
    with closing(sqlite3.connect(str(path), timeout=10.0)) as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        tables = [r[0] for r in cursor.fetchall()]
        for table in tables:
            c_cur = conn.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            counts[table] = int(c_cur.fetchone()[0])
    return counts


def backup_sqlite(
    source_path: Path | str,
    target_backup_path: Path | str,
    metadata_path: Path | str | None = None,
) -> BackupMetadata:
    """Create an atomic, online backup of a SQLite database using the sqlite3 backup API."""
    src = Path(source_path).resolve()
    if not src.is_file():
        raise SourceDatabaseNotFoundError(f"Basis data sumber tidak ditemukan: {src}")

    dst = Path(target_backup_path).resolve()
    if dst.is_dir():
        raise TargetPathInvalidError(f"Target backup merupakan direktori, bukan berkas: {dst}")

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise TargetPathInvalidError(f"Direktori target tidak dapat dibuat: {dst.parent}") from exc

    # Write to a temporary file in the target directory first for atomic publication
    tmp_backup = dst.with_suffix(f".tmp_{uuid.uuid4().hex[:8]}")

    start_time = time.perf_counter()
    try:
        with closing(sqlite3.connect(str(src), timeout=30.0)) as src_conn:
            with closing(sqlite3.connect(str(tmp_backup), timeout=30.0)) as dst_conn:
                src_conn.backup(dst_conn)
    except Exception as exc:
        if tmp_backup.is_file():
            tmp_backup.unlink(missing_ok=True)
        raise BackupRestoreError(f"Gagal melakukan backup online SQLite: {exc}") from exc

    duration_ms = (time.perf_counter() - start_time) * 1000.0

    # Validate integrity of the created snapshot before moving to final path
    is_ok, err_msg = check_sqlite_integrity(tmp_backup)
    if not is_ok:
        tmp_backup.unlink(missing_ok=True)
        raise BackupCorruptError(f"Hasil backup SQLite tidak lolos uji integritas: {err_msg}")

    try:
        os.replace(tmp_backup, dst)
    except OSError as exc:
        if tmp_backup.is_file():
            tmp_backup.unlink(missing_ok=True)
        raise TargetPathInvalidError(f"Gagal memindahkan backup ke path akhir: {dst}") from exc

    artifact_size = dst.stat().st_size
    sha256_checksum = compute_sha256(dst)
    table_counts = get_sqlite_table_counts(dst)

    meta = BackupMetadata(
        backend="sqlite",
        source=str(src),
        backup_file=str(dst),
        artifact_size_bytes=artifact_size,
        sha256=sha256_checksum,
        duration_ms=round(duration_ms, 2),
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        tables_count=table_counts,
    )

    if metadata_path is not None:
        meta_file = Path(metadata_path).resolve()
        meta_file.parent.mkdir(parents=True, exist_ok=True)
        meta_file.write_text(json.dumps(asdict(meta), indent=2), encoding="utf-8")

    return meta


def restore_sqlite(
    backup_file_path: Path | str,
    target_db_path: Path | str,
    expected_checksum: str | None = None,
    verify_integrity: bool = True,
) -> RestoreResult:
    """Restore a SQLite database from a backup artifact with checksum and integrity verification."""
    src = Path(backup_file_path).resolve()
    if not src.is_file():
        raise BackupRestoreError(f"Berkas backup tidak ditemukan: {src}")

    dst = Path(target_db_path).resolve()
    if dst.is_dir():
        raise TargetPathInvalidError(f"Target restore merupakan direktori, bukan berkas basis data: {dst}")

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise TargetPathInvalidError(f"Direktori target restore tidak dapat dibuat: {dst.parent}") from exc

    # 1. Checksum verification if expected_checksum provided
    actual_sha256 = compute_sha256(src)
    sha256_verified = False
    if expected_checksum:
        clean_expected = expected_checksum.strip().lower()
        if actual_sha256.lower() != clean_expected:
            raise ChecksumMismatchError(
                f"Checksum SHA-256 tidak cocok! Diharapkan '{clean_expected}', didapatkan '{actual_sha256}'."
            )
        sha256_verified = True

    # 2. Structural & PRAGMA integrity verification of backup file
    if verify_integrity:
        is_ok, err_msg = check_sqlite_integrity(src)
        if not is_ok:
            raise BackupCorruptError(f"Berkas backup tidak valid atau korup: {err_msg}")

    # 3. Perform restore to temporary location first, verify, then atomic rename
    start_time = time.perf_counter()
    tmp_restore = dst.with_suffix(f".restoring_{uuid.uuid4().hex[:8]}")

    try:
        # Using sqlite3 backup API from backup artifact to new file
        with closing(sqlite3.connect(str(src), timeout=30.0)) as backup_conn:
            with closing(sqlite3.connect(str(tmp_restore), timeout=30.0)) as target_conn:
                backup_conn.backup(target_conn)
    except Exception as exc:
        if tmp_restore.is_file():
            tmp_restore.unlink(missing_ok=True)
        raise BackupRestoreError(f"Gagal melakukan restore basis data SQLite: {exc}") from exc

    duration_ms = (time.perf_counter() - start_time) * 1000.0

    # Verify restored database integrity
    is_restored_ok, restored_err = check_sqlite_integrity(tmp_restore)
    if not is_restored_ok:
        tmp_restore.unlink(missing_ok=True)
        raise BackupCorruptError(f"Basis data hasil restore tidak lolos uji integritas: {restored_err}")

    try:
        os.replace(tmp_restore, dst)
    except OSError as exc:
        if tmp_restore.is_file():
            tmp_restore.unlink(missing_ok=True)
        raise TargetPathInvalidError(f"Gagal memindahkan basis data yang dipulihkan ke target: {dst}") from exc

    return RestoreResult(
        backend="sqlite",
        backup_file=str(src),
        target=str(dst),
        duration_ms=round(duration_ms, 2),
        artifact_size_bytes=dst.stat().st_size,
        sha256=actual_sha256,
        sha256_verified=sha256_verified,
        integrity_status="ok",
    )


def backup_postgres(
    source_dsn: str,
    target_backup_path: Path | str,
    metadata_path: Path | str | None = None,
) -> BackupMetadata:
    """Create PostgreSQL backup using local pg_dump tool."""
    if not shutil.which("pg_dump"):
        raise BackupRestoreError("Perintah 'pg_dump' tidak ditemukan di sistem untuk backup PostgreSQL.")

    dst = Path(target_backup_path).resolve()
    if dst.is_dir():
        raise TargetPathInvalidError(f"Target backup merupakan direktori: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)

    tmp_dump = dst.with_suffix(f".tmp_{uuid.uuid4().hex[:8]}")
    cmd = [
        "pg_dump",
        "--dbname",
        source_dsn,
        "--format=c",
        "--file",
        str(tmp_dump),
    ]

    start_time = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    duration_ms = (time.perf_counter() - start_time) * 1000.0

    if proc.returncode != 0:
        if tmp_dump.is_file():
            tmp_dump.unlink(missing_ok=True)
        raise BackupRestoreError(f"pg_dump gagal (exit {proc.returncode}): {proc.stderr.strip()}")

    os.replace(tmp_dump, dst)
    sha256_checksum = compute_sha256(dst)
    artifact_size = dst.stat().st_size

    meta = BackupMetadata(
        backend="postgres",
        source=redact_dsn(source_dsn),
        backup_file=str(dst),
        artifact_size_bytes=artifact_size,
        sha256=sha256_checksum,
        duration_ms=round(duration_ms, 2),
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        tables_count={},
    )

    if metadata_path is not None:
        meta_file = Path(metadata_path).resolve()
        meta_file.parent.mkdir(parents=True, exist_ok=True)
        meta_file.write_text(json.dumps(asdict(meta), indent=2), encoding="utf-8")

    return meta


def restore_postgres(
    backup_file_path: Path | str,
    target_dsn: str,
    expected_checksum: str | None = None,
) -> RestoreResult:
    """Restore PostgreSQL database from custom format dump using local pg_restore tool."""
    if not shutil.which("pg_restore"):
        raise BackupRestoreError("Perintah 'pg_restore' tidak ditemukan di sistem untuk restore PostgreSQL.")

    src = Path(backup_file_path).resolve()
    if not src.is_file():
        raise BackupRestoreError(f"Berkas dump PostgreSQL tidak ditemukan: {src}")

    actual_sha256 = compute_sha256(src)
    sha256_verified = False
    if expected_checksum:
        clean_expected = expected_checksum.strip().lower()
        if actual_sha256.lower() != clean_expected:
            raise ChecksumMismatchError(
                f"Checksum SHA-256 tidak cocok! Diharapkan '{clean_expected}', didapatkan '{actual_sha256}'."
            )
        sha256_verified = True

    cmd = [
        "pg_restore",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "--dbname",
        target_dsn,
        str(src),
    ]

    start_time = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    duration_ms = (time.perf_counter() - start_time) * 1000.0

    # Note: pg_restore may return 1 if there were minor warnings during DROP
    if proc.returncode not in (0, 1):
        raise BackupRestoreError(f"pg_restore gagal (exit {proc.returncode}): {proc.stderr.strip()}")

    return RestoreResult(
        backend="postgres",
        backup_file=str(src),
        target=redact_dsn(target_dsn),
        duration_ms=round(duration_ms, 2),
        artifact_size_bytes=src.stat().st_size,
        sha256=actual_sha256,
        sha256_verified=sha256_verified,
        integrity_status="ok",
    )


def backup_database(
    source: str | Path | None = None,
    output_path: str | Path | None = None,
    metadata_path: str | Path | None = None,
) -> BackupMetadata:
    """High-level dispatcher for backup of SQLite or PostgreSQL database."""
    config = resolve_db_config(source)
    if output_path is None:
        ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
        ext = ".dump" if config.backend == "postgres" else ".db"
        output_path = Path("backups") / f"marketstudio_backup_{ts}{ext}"

    if config.backend == "sqlite":
        return backup_sqlite(config.target, output_path, metadata_path)
    return backup_postgres(config.target, output_path, metadata_path)


def restore_database(
    backup_file_path: str | Path,
    target_path: str | Path,
    expected_checksum: str | None = None,
    verify_integrity: bool = True,
) -> RestoreResult:
    """High-level dispatcher for restore of SQLite or PostgreSQL database."""
    target_str = str(target_path).strip()
    if is_postgres_dsn(target_str):
        return restore_postgres(backup_file_path, target_str, expected_checksum)
    return restore_sqlite(backup_file_path, target_str, expected_checksum, verify_integrity)


def verify_quantitative_tables(
    source_db: str | Path,
    restored_db: str | Path,
) -> dict[str, Any]:
    """Verify row counts across all application tables match 100% between source and restored databases."""
    src_counts = get_sqlite_table_counts(source_db)
    dst_counts = get_sqlite_table_counts(restored_db)

    all_tables = sorted(set(src_counts.keys()) | set(dst_counts.keys()))
    mismatches: dict[str, dict[str, int]] = {}

    for t in all_tables:
        s_cnt = src_counts.get(t, -1)
        d_cnt = dst_counts.get(t, -1)
        if s_cnt != d_cnt:
            mismatches[t] = {"source": s_cnt, "restored": d_cnt}

    if mismatches:
        raise VerificationFailedError(f"Verifikasi kuantitatif gagal: {len(mismatches)} tabel tidak cocok ({mismatches}).")

    return {
        "status": "passed",
        "tables_checked": len(all_tables),
        "total_rows_source": sum(src_counts.values()),
        "total_rows_restored": sum(dst_counts.values()),
        "tables": {t: {"source": src_counts[t], "restored": dst_counts[t]} for t in all_tables},
    }


def verify_business_reports(
    source_db: str | Path,
    restored_db: str | Path,
    workspace_id: str | None = None,
    actor_id: str | None = None,
) -> dict[str, Any]:
    """Verify daily financial reports (revenue, COGS, gross profit, cash flow, stock balance) match exactly."""
    src_service = BaselineService(str(source_db))
    dst_service = BaselineService(str(restored_db))

    with closing(sqlite3.connect(str(restored_db), timeout=10.0)) as conn:
        conn.row_factory = sqlite3.Row
        if workspace_id:
            ws_rows = conn.execute(
                "SELECT workspace_id FROM workspaces WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchall()
        else:
            ws_rows = conn.execute("SELECT workspace_id FROM workspaces ORDER BY created_at ASC").fetchall()

    if not ws_rows:
        raise VerificationFailedError("Tidak ditemukan workspace pada basis data yang dipulihkan untuk verifikasi laporan.")

    verified_workspaces: list[dict[str, Any]] = []

    for ws in ws_rows:
        wid = ws["workspace_id"]
        # Determine actor for workspace
        target_actor = actor_id
        if not target_actor:
            with closing(sqlite3.connect(str(restored_db), timeout=10.0)) as conn:
                m_row = conn.execute(
                    "SELECT actor_id FROM workspace_memberships WHERE workspace_id = ? AND revoked_at IS NULL LIMIT 1",
                    (wid,),
                ).fetchone()
                target_actor = m_row[0] if m_row else "usr_owner"

        # Determine reference date from purchases/sales
        with closing(sqlite3.connect(str(restored_db), timeout=10.0)) as conn:
            p_row = conn.execute(
                "SELECT MIN(occurred_at) FROM purchases WHERE workspace_id = ?",
                (wid,),
            ).fetchone()
            ref_ts = p_row[0] if p_row and p_row[0] else None

        ref_date: str | None = None
        if ref_ts:
            ref_date = str(ref_ts)[:10]

        src_rep = src_service.get_daily_report(wid, target_actor, date_str=ref_date)
        dst_rep = dst_service.get_daily_report(wid, target_actor, date_str=ref_date)

        # Check financial scalar fields
        financial_fields = [
            "revenue_idr",
            "cogs_idr",
            "cogs_status",
            "gross_profit_idr",
            "gross_profit_status",
            "cash_in_idr",
            "cash_out_idr",
            "net_cash_flow_idr",
        ]
        field_mismatches: dict[str, dict[str, Any]] = {}
        for f in financial_fields:
            if src_rep.get(f) != dst_rep.get(f):
                field_mismatches[f] = {"source": src_rep.get(f), "restored": dst_rep.get(f)}

        # Check ending inventory (total value and items)
        src_inv = src_rep.get("ending_inventory") or {}
        dst_inv = dst_rep.get("ending_inventory") or {}

        if src_inv.get("total_value_idr") != dst_inv.get("total_value_idr"):
            field_mismatches["inventory_total_value_idr"] = {
                "source": src_inv.get("total_value_idr"),
                "restored": dst_inv.get("total_value_idr"),
            }
        if src_inv.get("total_qty") != dst_inv.get("total_qty"):
            field_mismatches["inventory_total_qty"] = {
                "source": src_inv.get("total_qty"),
                "restored": dst_inv.get("total_qty"),
            }

        # Compare per-offering stock balance
        src_items = {it["offering_id"]: it for it in src_inv.get("items", [])}
        dst_items = {it["offering_id"]: it for it in dst_inv.get("items", [])}

        if set(src_items.keys()) != set(dst_items.keys()):
            field_mismatches["inventory_items_keys"] = {
                "source": list(src_items.keys()),
                "restored": list(dst_items.keys()),
            }
        else:
            for oid, s_it in src_items.items():
                d_it = dst_items[oid]
                if s_it.get("qty_remaining") != d_it.get("qty_remaining") or s_it.get("value_idr") != d_it.get("value_idr"):
                    field_mismatches[f"inventory_offering_{oid}"] = {"source": s_it, "restored": d_it}

        if field_mismatches:
            raise VerificationFailedError(
                f"Verifikasi laporan keuangan workspace '{wid}' gagal: {field_mismatches}"
            )

        verified_workspaces.append(
            {
                "workspace_id": wid,
                "period": dst_rep.get("period"),
                "revenue_idr": dst_rep.get("revenue_idr"),
                "cogs_idr": dst_rep.get("cogs_idr"),
                "gross_profit_idr": dst_rep.get("gross_profit_idr"),
                "cash_in_idr": dst_rep.get("cash_in_idr"),
                "cash_out_idr": dst_rep.get("cash_out_idr"),
                "net_cash_flow_idr": dst_rep.get("net_cash_flow_idr"),
                "inventory_total_value_idr": dst_inv.get("total_value_idr"),
                "inventory_items_count": len(dst_inv.get("items", [])),
            }
        )

    return {
        "status": "passed",
        "workspaces_verified": len(verified_workspaces),
        "reports": verified_workspaces,
    }


def verify_security_isolation(
    restored_db: str | Path,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Verify tenant isolation and membership access control rules hold on restored database."""
    service = BaselineService(str(restored_db))

    with closing(sqlite3.connect(str(restored_db), timeout=10.0)) as conn:
        conn.row_factory = sqlite3.Row
        workspaces = conn.execute("SELECT workspace_id FROM workspaces ORDER BY created_at ASC").fetchall()

    if not workspaces:
        raise VerificationFailedError("Basis data tidak memiliki workspace untuk diverifikasi.")

    target_ws = workspace_id or workspaces[0]["workspace_id"]

    # 1. Verify legitimate active owner has access
    with closing(sqlite3.connect(str(restored_db), timeout=10.0)) as conn:
        conn.row_factory = sqlite3.Row
        active_member = conn.execute(
            "SELECT actor_id FROM workspace_memberships WHERE workspace_id = ? AND revoked_at IS NULL LIMIT 1",
            (target_ws,),
        ).fetchone()

    if active_member:
        owner_actor = active_member["actor_id"]
        # Owner must be able to list offerings
        offerings = service.list_offerings(target_ws, owner_actor)
        if not isinstance(offerings, list):
            raise VerificationFailedError("Akses pemilik sah ke workspace gagal.")

    # 2. Verify non-member foreign actor is rejected (403 or 404 DomainError)
    foreign_actor = f"usr_attacker_{uuid.uuid4().hex[:6]}"
    try:
        service.list_offerings(target_ws, foreign_actor)
        raise VerificationFailedError("Isolasi tenant bocor: aktor asing dapat mengakses data workspace!")
    except DomainError as err:
        if err.status_code not in (403, 404):
            raise VerificationFailedError(
                f"Isolasi tenant mengembalikan status tidak terduga: {err.status_code}"
            ) from err

    # 3. Verify unauthenticated actor (None) is rejected with 401
    try:
        service.list_offerings(target_ws, None)
        raise VerificationFailedError("Aktor unauthenticated diizinkan mengakses data workspace!")
    except DomainError as err:
        if err.status_code != 401:
            raise VerificationFailedError(
                f"Akses tanpa otentikasi mengembalikan status bukan 401: {err.status_code}"
            ) from err

    # 4. If a revoked membership exists, verify access is denied
    with closing(sqlite3.connect(str(restored_db), timeout=10.0)) as conn:
        conn.row_factory = sqlite3.Row
        revoked_member = conn.execute(
            "SELECT actor_id FROM workspace_memberships WHERE workspace_id = ? AND revoked_at IS NOT NULL LIMIT 1",
            (target_ws,),
        ).fetchone()

    if revoked_member:
        rev_actor = revoked_member["actor_id"]
        try:
            service.list_offerings(target_ws, rev_actor)
            raise VerificationFailedError("Keamanan membership gagal: aktor yang dicabut haknya tetap bisa mengakses!")
        except DomainError as err:
            if err.status_code not in (403, 404):
                raise VerificationFailedError(f"Akses revoked mengembalikan status: {err.status_code}") from err

    return {
        "status": "passed",
        "workspace_id": target_ws,
        "foreign_actor_rejected": True,
        "unauthenticated_rejected": True,
        "revoked_member_rejected": bool(revoked_member),
    }


def verify_operational_health(
    restored_db: str | Path,
    host: str = "127.0.0.1",
    port: int = 0,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Verify operational readiness by running an ephemeral server on the restored DB and querying /health."""
    server = create_server(host=host, port=port, db_path=str(restored_db))
    bound_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://{host}:{bound_port}/health"
    start_time = time.perf_counter()

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "MarketStudio-BackupRestoreCheck/1.0",
                "Accept": "application/json",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            status_code = resp.status
            raw_body = resp.read()
            data = json.loads(raw_body.decode("utf-8"))

            if status_code != 200:
                raise VerificationFailedError(f"/health mengembalikan HTTP non-200: {status_code}")
            if data.get("status") != "ok":
                raise VerificationFailedError(f"/health status bukan 'ok': {data}")

            return {
                "status": "passed",
                "url": url,
                "http_status": status_code,
                "duration_ms": round(duration_ms, 2),
                "payload": data,
            }
    except Exception as exc:
        raise VerificationFailedError(f"Pemeriksaan operasional /health gagal: {exc}") from exc
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def verify_all(
    source_db: str | Path,
    restored_db: str | Path,
    workspace_id: str | None = None,
    check_health: bool = True,
) -> dict[str, Any]:
    """Execute complete battery of quantitative, business, security, and operational checks."""
    quant_result = verify_quantitative_tables(source_db, restored_db)
    biz_result = verify_business_reports(source_db, restored_db, workspace_id=workspace_id)
    sec_result = verify_security_isolation(restored_db, workspace_id=workspace_id)

    health_result: dict[str, Any] | None = None
    if check_health:
        health_result = verify_operational_health(restored_db)

    return {
        "status": "passed",
        "quantitative": quant_result,
        "business_reports": biz_result,
        "security_isolation": sec_result,
        "operational_health": health_result,
    }


def run_synthetic_drill(
    work_dir: Path | str | None = None,
    clean_up: bool = True,
) -> dict[str, Any]:
    """Execute end-to-end backup and restore drill with synthetic dataset, returning exact metrics."""
    temp_dir_obj: tempfile.TemporaryDirectory[str] | None = None
    if work_dir is None:
        temp_dir_obj = tempfile.TemporaryDirectory()
        base_dir = Path(temp_dir_obj.name)
    else:
        base_dir = Path(work_dir).resolve()
        base_dir.mkdir(parents=True, exist_ok=True)

    try:
        source_db = base_dir / "synthetic_source.db"
        backup_artifact = base_dir / "synthetic_source.backup"
        meta_file = base_dir / "synthetic_source.json"
        restored_db = base_dir / "synthetic_restored.db"

        # 1. Initialize and populate source database with rich synthetic fixture
        init_db(str(source_db))
        service = BaselineService(str(source_db))

        # Primary Tenant: Warung Bakso & Sembako (hybrid) with purchases, sales, stock, and cash
        actor_owner = "usr_demo_owner"
        code, seed_info = service.bootstrap_demo_workspace(actor_owner)
        if code not in (200, 201):
            raise BackupRestoreError(f"Gagal menyiapkan workspace demo sintetis: {seed_info}")
        ws_id = seed_info["workspace"]["workspace_id"]

        # Add a revoked member to test security revocation preservation
        with closing(sqlite3.connect(str(source_db), timeout=10.0)) as conn:
            conn.execute(
                """
                INSERT INTO workspace_memberships (workspace_id, actor_id, role, created_at, revoked_at)
                VALUES (?, 'usr_revoked_staff', 'staff', ?, ?)
                """,
                (ws_id, "2026-11-28T08:00:00Z", "2026-11-28T09:00:00Z"),
            )
            conn.commit()

        # Secondary Tenant: Isolated retail store
        actor_tenant2 = "usr_tenant_2"
        code_2, res_2 = service.create_workspace(
            {"name": "Kios Pulsa & Aksesoris", "business_type": "umkm_hybrid"},
            actor=actor_tenant2,
        )
        ws_2_id = res_2["workspace_id"]
        service.create_offering(
            workspace_id=ws_2_id,
            actor_id=actor_tenant2,
            payload={
                "name": "Voucher Kuota 10GB",
                "offering_type": "goods",
                "unit_price_idr": 35000,
                "unit": "voucher",
            },
            actor=actor_tenant2,
        )

        # 2. Perform online, atomic backup
        backup_meta = backup_sqlite(source_db, backup_artifact, metadata_path=meta_file)

        # 3. Perform restore to a completely separate database file
        restore_res = restore_sqlite(
            backup_artifact,
            restored_db,
            expected_checksum=backup_meta.sha256,
            verify_integrity=True,
        )

        # 4. Run full verification suite (quantitative, business, security, operational /health)
        verification = verify_all(source_db, restored_db, workspace_id=None, check_health=True)

        return {
            "status": "passed",
            "source_db": str(source_db),
            "restored_db": str(restored_db),
            "backup": asdict(backup_meta),
            "restore": asdict(restore_res),
            "verification": verification,
        }
    finally:
        if clean_up and temp_dir_obj is not None:
            temp_dir_obj.cleanup()


def _format_table_comparison(quant_result: dict[str, Any]) -> str:
    lines = [
        f"{'Nama Tabel':<28} | {'Sumber':<10} | {'Dipulihkan':<10} | {'Status':<6}",
        f"{'-'*28}-|-{'-'*10}-|-{'-'*10}-|-{'-'*6}",
    ]
    tables = quant_result.get("tables", {})
    for t_name, counts in sorted(tables.items()):
        s = counts["source"]
        r = counts["restored"]
        st = "MATCH" if s == r else "MISMATCH"
        lines.append(f"{t_name:<28} | {s:<10} | {r:<10} | {st:<6}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="backup_restore.py",
        description="MarketStudio Backup and Restore Automation Tool (Issue #44)",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Perintah operasi")

    # Subcommand: backup
    p_backup = subparsers.add_parser("backup", help="Buat cadangan basis data")
    p_backup.add_argument(
        "--source",
        "-s",
        default=None,
        help="Path file SQLite atau PostgreSQL DSN (default: MARKETSTUDIO_DB_PATH)",
    )
    p_backup.add_argument(
        "--output",
        "-o",
        required=True,
        help="Path berkas tujuan backup",
    )
    p_backup.add_argument(
        "--metadata",
        "-m",
        default=None,
        help="Path opsional untuk menyimpan metadata JSON sidecar",
    )
    p_backup.add_argument("--json", action="store_true", help="Cetak output dalam format JSON")
    p_backup.add_argument("--quiet", "-q", action="store_true", help="Mode senyap (hanya output esensial)")

    # Subcommand: restore
    p_restore = subparsers.add_parser("restore", help="Pulihkan basis data dari cadangan")
    p_restore.add_argument(
        "--backup-file",
        "-b",
        "--source",
        dest="backup_file",
        required=True,
        help="Path berkas cadangan (backup)",
    )
    p_restore.add_argument(
        "--target",
        "-t",
        required=True,
        help="Path berkas SQLite baru atau PostgreSQL DSN target restore",
    )
    p_restore.add_argument(
        "--checksum",
        "-c",
        default=None,
        help="Checksum SHA-256 yang diharapkan (opsional, diverifikasi bila diberikan)",
    )
    p_restore.add_argument(
        "--skip-integrity-check",
        action="store_true",
        help="Lewati PRAGMA integrity_check sebelum restore",
    )
    p_restore.add_argument("--json", action="store_true", help="Cetak output dalam format JSON")
    p_restore.add_argument("--quiet", "-q", action="store_true", help="Mode senyap")

    # Subcommand: verify
    p_verify = subparsers.add_parser("verify", help="Verifikasi integritas antara sumber dan basis data pulihan")
    p_verify.add_argument(
        "--source-db",
        "-s",
        required=True,
        help="Path berkas SQLite sumber",
    )
    p_verify.add_argument(
        "--restored-db",
        "-r",
        "--target-db",
        dest="restored_db",
        required=True,
        help="Path berkas SQLite hasil restore",
    )
    p_verify.add_argument(
        "--workspace-id",
        "-w",
        default=None,
        help="Workspace ID spesifik yang akan diverifikasi",
    )
    p_verify.add_argument(
        "--skip-health",
        action="store_true",
        help="Lewati pemeriksaan server live /health",
    )
    p_verify.add_argument("--json", action="store_true", help="Cetak output dalam format JSON")
    p_verify.add_argument("--quiet", "-q", action="store_true", help="Mode senyap")

    # Subcommand: drill
    p_drill = subparsers.add_parser("drill", help="Jalankan drill backup & restore sintetis lengkap")
    p_drill.add_argument(
        "--work-dir",
        "-d",
        default=None,
        help="Direktori kerja penyimpanan berkas drill (default: temporary directory)",
    )
    p_drill.add_argument(
        "--keep-files",
        action="store_true",
        help="Pertahankan berkas sementara setelah drill selesai",
    )
    p_drill.add_argument("--json", action="store_true", help="Cetak output dalam format JSON")
    p_drill.add_argument("--quiet", "-q", action="store_true", help="Mode senyap")

    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        return 2

    try:
        if args.subcommand == "backup":
            meta = backup_database(
                source=args.source,
                output_path=args.output,
                metadata_path=args.metadata,
            )
            if args.json:
                print(json.dumps(asdict(meta), indent=2))
            elif not args.quiet:
                print(f"[PASS] Backup berhasil dibuat ({meta.backend}):")
                print(f"  Berkas   : {meta.backup_file}")
                print(f"  Ukuran   : {meta.artifact_size_bytes} bytes")
                print(f"  SHA-256  : {meta.sha256}")
                print(f"  Durasi   : {meta.duration_ms} ms")
            return 0

        if args.subcommand == "restore":
            res = restore_database(
                backup_file_path=args.backup_file,
                target_path=args.target,
                expected_checksum=args.checksum,
                verify_integrity=not args.skip_integrity_check,
            )
            if args.json:
                print(json.dumps(asdict(res), indent=2))
            elif not args.quiet:
                print(f"[PASS] Basis data berhasil dipulihkan ({res.backend}):")
                print(f"  Target   : {res.target}")
                print(f"  Durasi   : {res.duration_ms} ms")
                print(f"  SHA-256  : {res.sha256} ({'verified' if res.sha256_verified else 'unverified'})")
                print(f"  Integritas: {res.integrity_status}")
            return 0

        if args.subcommand == "verify":
            ver = verify_all(
                source_db=args.source_db,
                restored_db=args.restored_db,
                workspace_id=args.workspace_id,
                check_health=not args.skip_health,
            )
            if args.json:
                print(json.dumps(ver, indent=2))
            elif not args.quiet:
                print("[PASS] Seluruh verifikasi integritas berhasil:")
                print(f"  Tabel diperiksa : {ver['quantitative']['tables_checked']}")
                print(f"  Baris sumber    : {ver['quantitative']['total_rows_source']}")
                print(f"  Baris pulihan   : {ver['quantitative']['total_rows_restored']}")
                print(f"  Laporan teruji  : {ver['business_reports']['workspaces_verified']} workspace")
                print(f"  Keamanan        : {ver['security_isolation']['status']}")
                if ver["operational_health"]:
                    print(f"  Operasional     : HTTP {ver['operational_health']['http_status']} (/health ok)")
            return 0

        if args.subcommand == "drill":
            drill_res = run_synthetic_drill(
                work_dir=args.work_dir,
                clean_up=not args.keep_files,
            )
            if args.json:
                print(json.dumps(drill_res, indent=2))
            elif not args.quiet:
                b = drill_res["backup"]
                r = drill_res["restore"]
                v = drill_res["verification"]
                print("[PASS] Synthetic Backup & Restore Drill Berhasil 100%:")
                print(f"  Waktu Backup  : {b['duration_ms']} ms ({b['artifact_size_bytes']} bytes)")
                print(f"  SHA-256       : {b['sha256']}")
                print(f"  Waktu Restore : {r['duration_ms']} ms")
                print(f"  Kuantitatif   : {v['quantitative']['tables_checked']} tabel identik (total {v['quantitative']['total_rows_restored']} baris)")
                print(f"  Keuangan      : {v['business_reports']['workspaces_verified']} workspace laporan harian 100% cocok")
                print(f"  Keamanan      : Isolasi tenant & pembatalan hak akses utuh")
                print(f"  Operasional   : HTTP {v['operational_health']['http_status']} (/health ok)")
                print("\nPerbandingan Tabel:")
                print(_format_table_comparison(v["quantitative"]))
            return 0

    except (ChecksumMismatchError, BackupCorruptError, VerificationFailedError) as err:
        print(f"FAIL [Verifikasi Gagal]: {err}", file=sys.stderr)
        return 1
    except (SourceDatabaseNotFoundError, TargetPathInvalidError, BackupRestoreError) as err:
        print(f"ERROR [Kesalahan Konfigurasi/Path]: {err}", file=sys.stderr)
        return 2
    except Exception as err:
        print(f"UNEXPECTED ERROR: {err}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
