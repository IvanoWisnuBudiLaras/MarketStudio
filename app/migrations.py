"""Versioned PostgreSQL / Supabase migration discovery, verification, apply, and rollback runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.db import (
    _import_psycopg,
    build_psycopg_connect_kwargs,
    is_postgres_dsn,
    redact_dsn,
    resolve_db_config,
)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations" / "postgres"
_MIGRATION_FILE_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.(up|down)\.sql$")
_MIGRATION_LOCK_KEY = "marketstudio:migrations"


class MigrationError(RuntimeError):
    """Raised on invalid migration files, checksum drift, or failed migration operations."""


@dataclass(frozen=True)
class MigrationSpec:
    """Ordered up/down SQL migration pair with deterministic SHA-256 checksum."""

    version: str
    name: str
    up_path: Path
    down_path: Path
    checksum: str


def discover_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[MigrationSpec]:
    """Discover and validate ordered pairs of .up.sql and .down.sql migration files."""
    if not migrations_dir.is_dir():
        raise MigrationError(f"Direktori migrasi tidak ditemukan: {migrations_dir}")

    grouped: dict[str, dict[str, Any]] = {}
    for entry in sorted(migrations_dir.iterdir()):
        if entry.is_dir() or entry.name.startswith("."):
            continue
        match = _MIGRATION_FILE_RE.match(entry.name)
        if not match:
            raise MigrationError(
                f"Nama file migrasi tidak valid '{entry.name}' (harus NNNN_nama.(up|down).sql)."
            )
        version, name, direction = match.groups()
        bucket = grouped.setdefault(version, {"name": name, "up": None, "down": None})
        if bucket["name"] != name:
            raise MigrationError(
                f"Nama migrasi versi {version} tidak konsisten antara up dan down ('{bucket['name']}' vs '{name}')."
            )
        if bucket[direction] is not None:
            raise MigrationError(f"Duplikat file {direction} untuk versi migrasi {version}.")
        bucket[direction] = entry

    specs: list[MigrationSpec] = []
    for version in sorted(grouped):
        bucket = grouped[version]
        up_path: Path | None = bucket["up"]
        down_path: Path | None = bucket["down"]
        if up_path is None or down_path is None:
            raise MigrationError(f"Versi migrasi {version} wajib memiliki pasangan .up.sql dan .down.sql.")

        up_sql = up_path.read_text(encoding="utf-8")
        down_sql = down_path.read_text(encoding="utf-8")
        if not up_sql.strip():
            raise MigrationError(f"File migrasi kosong: {up_path.name}")
        if not down_sql.strip():
            raise MigrationError(f"File rollback kosong: {down_path.name}")

        checksum = hashlib.sha256(up_sql.encode("utf-8")).hexdigest()
        specs.append(
            MigrationSpec(
                version=version,
                name=bucket["name"],
                up_path=up_path,
                down_path=down_path,
                checksum=checksum,
            )
        )
    return specs


def resolve_migration_database_url(database_url: str | None = None) -> str:
    """Resolve explicit or env-configured PostgreSQL DSN for migrations."""
    raw = (
        database_url
        or os.environ.get("MIGRATION_DATABASE_URL")
        or os.environ.get("DIRECT_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("MARKETSTUDIO_DATABASE_URL")
        or ""
    ).strip()
    if not raw:
        raise MigrationError(
            "Database URL tidak ditemukan. Berikan --database-url atau set DIRECT_DATABASE_URL / DATABASE_URL."
        )
    if not is_postgres_dsn(raw):
        raise MigrationError("Database URL migrasi harus menggunakan skema postgres:// atau postgresql://.")
    return raw


def _open_migration_connection(database_url: str) -> Any:
    psycopg, _ = _import_psycopg()
    config = resolve_db_config(database_url=database_url)
    kwargs = build_psycopg_connect_kwargs(config)
    return psycopg.connect(config.target, **kwargs)


def ensure_migrations_table(conn: Any) -> None:
    """Create schema_migrations tracking table if it does not exist."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )


def _fetch_applied_rows(conn: Any) -> list[dict[str, str]]:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('schema_migrations')")
        reg = cur.fetchone()
        if not reg or reg[0] is None:
            return []
        cur.execute("SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version ASC")
        return [
            {
                "version": row[0],
                "name": row[1],
                "checksum": row[2],
                "applied_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
            }
            for row in cur.fetchall()
        ]


def inspect_migration_state(conn: Any, migrations_dir: Path = MIGRATIONS_DIR) -> dict[str, Any]:
    """Read-only inspection of schema_migrations against local migration files (no DDL)."""
    specs = discover_migrations(migrations_dir)
    spec_map = {s.version: s for s in specs}
    applied = _fetch_applied_rows(conn)
    applied_map = {item["version"]: item for item in applied}

    mismatches: list[str] = []
    for item in applied:
        ver = item["version"]
        spec = spec_map.get(ver)
        if spec is None:
            mismatches.append(f"Applied version {ver} tidak ada di direktori migrasi.")
        elif spec.checksum != item["checksum"]:
            mismatches.append(f"Checksum migrasi {ver}_{spec.name} berubah setelah diterapkan.")

    pending = [s.version for s in specs if s.version not in applied_map]
    return {
        "applied": applied,
        "pending": pending,
        "checksum_mismatches": mismatches,
        "current": len(pending) == 0 and len(mismatches) == 0,
    }


def verify_migrations_current(
    conn: Any,
    migrations_dir: Path = MIGRATIONS_DIR,
) -> tuple[bool, list[str], list[str]]:
    """Verify whether all discovered migrations are applied without checksum drift (read-only)."""
    state = inspect_migration_state(conn, migrations_dir=migrations_dir)
    if state["checksum_mismatches"]:
        raise MigrationError("; ".join(state["checksum_mismatches"]))
    return state["current"], state["pending"], state["checksum_mismatches"]


def get_migration_status(
    database_url: str,
    migrations_dir: Path = MIGRATIONS_DIR,
) -> dict[str, Any]:
    """Return migration status for the target PostgreSQL database (redacted target, read-only)."""
    dsn = resolve_migration_database_url(database_url)
    conn = _open_migration_connection(dsn)
    try:
        state = inspect_migration_state(conn, migrations_dir=migrations_dir)
        conn.commit()
        return {"target": redact_dsn(dsn), **state}
    except Exception:
        if not conn.closed:
            conn.rollback()
        raise
    finally:
        conn.close()


def apply_migrations(
    database_url: str,
    migrations_dir: Path = MIGRATIONS_DIR,
) -> list[str]:
    """Apply all pending migrations atomically in version order under an advisory lock."""
    dsn = resolve_migration_database_url(database_url)
    specs = discover_migrations(migrations_dir)
    conn = _open_migration_connection(dsn)
    applied_now: list[str] = []
    lock_held = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (_MIGRATION_LOCK_KEY,))
        conn.commit()
        lock_held = True

        ensure_migrations_table(conn)
        conn.commit()

        state = inspect_migration_state(conn, migrations_dir=migrations_dir)
        conn.commit()
        if state["checksum_mismatches"]:
            raise MigrationError("; ".join(state["checksum_mismatches"]))

        applied_versions = {item["version"] for item in state["applied"]}
        for spec in specs:
            if spec.version in applied_versions:
                continue
            up_sql = spec.up_path.read_text(encoding="utf-8")
            try:
                with conn.cursor() as cur:
                    # Simple query protocol (no params) supports multi-statement SQL and DO $$ blocks.
                    cur.execute(up_sql)
                    cur.execute(
                        "INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                        (spec.version, spec.name, spec.checksum),
                    )
                conn.commit()
                applied_now.append(spec.version)
            except Exception:
                if not conn.closed:
                    conn.rollback()
                raise
        return applied_now
    finally:
        if lock_held and not conn.closed:
            try:
                conn.rollback()
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (_MIGRATION_LOCK_KEY,))
                conn.commit()
            except Exception:
                pass
        if not conn.closed:
            conn.close()


def rollback_migrations(
    database_url: str,
    *,
    steps: int = 1,
    to_version: str | None = None,
    migrations_dir: Path = MIGRATIONS_DIR,
) -> list[str]:
    """Roll back applied migrations in reverse order using explicit .down.sql scripts."""
    dsn = resolve_migration_database_url(database_url)
    specs = discover_migrations(migrations_dir)
    spec_map = {s.version: s for s in specs}

    if to_version is None:
        if steps < 1:
            raise MigrationError("steps untuk rollback harus >= 1.")
    else:
        if not re.match(r"^\d{4}$", to_version):
            raise MigrationError("to_version harus berupa 4 digit angka (contoh: '0000' atau '0001').")
        if to_version != "0000" and to_version not in spec_map:
            raise MigrationError(f"Target versi rollback '{to_version}' tidak dikenal.")

    conn = _open_migration_connection(dsn)
    rolled_back: list[str] = []
    lock_held = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (_MIGRATION_LOCK_KEY,))
        conn.commit()
        lock_held = True

        applied_desc = list(reversed(_fetch_applied_rows(conn)))
        conn.commit()
        if not applied_desc:
            return []

        if to_version is not None:
            targets = [item["version"] for item in applied_desc if item["version"] > to_version]
        else:
            targets = [item["version"] for item in applied_desc[:steps]]

        for ver in targets:
            spec = spec_map.get(ver)
            if spec is None:
                raise MigrationError(f"Tidak dapat rollback versi {ver}: file .down.sql tidak ditemukan.")
            down_sql = spec.down_path.read_text(encoding="utf-8")
            try:
                with conn.cursor() as cur:
                    cur.execute(down_sql)
                    cur.execute("DELETE FROM schema_migrations WHERE version = %s", (ver,))
                conn.commit()
                rolled_back.append(ver)
            except Exception:
                if not conn.closed:
                    conn.rollback()
                raise
        return rolled_back
    finally:
        if lock_held and not conn.closed:
            try:
                conn.rollback()
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (_MIGRATION_LOCK_KEY,))
                conn.commit()
            except Exception:
                pass
        if not conn.closed:
            conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MarketStudio PostgreSQL / Supabase migration runner")
    parser.add_argument(
        "--database-url",
        default=None,
        help="PostgreSQL DSN (default: MIGRATION_DATABASE_URL / DIRECT_DATABASE_URL / DATABASE_URL)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Inspect applied and pending migrations (read-only)")
    sub.add_parser("up", help="Apply all pending migrations")
    down_p = sub.add_parser("down", help="Rollback applied migrations using .down.sql")
    down_p.add_argument("--steps", type=int, default=1, help="Number of migrations to roll back (default: 1)")
    down_p.add_argument("--to", dest="to_version", default=None, help="Target version (e.g. 0001 or 0000)")

    args = parser.parse_args(argv)
    dsn = resolve_migration_database_url(args.database_url)

    if args.command == "status":
        print(json.dumps(get_migration_status(dsn), indent=2))
        return 0
    if args.command == "up":
        applied = apply_migrations(dsn)
        print(json.dumps({"target": redact_dsn(dsn), "applied": applied}, indent=2))
        return 0
    if args.command == "down":
        rolled_back = rollback_migrations(dsn, steps=args.steps, to_version=args.to_version)
        print(json.dumps({"target": redact_dsn(dsn), "rolled_back": rolled_back}, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
