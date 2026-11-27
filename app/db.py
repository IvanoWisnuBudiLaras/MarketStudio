"""Database configuration, dialect translation, and atomic transaction adapters (SQLite default + PostgreSQL)."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

from app.domain import DomainError

DEFAULT_DB_PATH = os.environ.get(
    "MARKETSTUDIO_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "marketstudio.db"),
)

_SENSITIVE_DSN_QUERY_KEYS = frozenset({"password", "pass", "pgpassword", "sslpassword"})
_LOCAL_PG_HOSTS = frozenset({"", "localhost", "127.0.0.1", "::1"})

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    business_type TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'IDR',
    timezone TEXT NOT NULL DEFAULT 'Asia/Jakarta',
    is_demo INTEGER NOT NULL DEFAULT 0,
    demo_slug TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspace_memberships (
    workspace_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'owner',
    created_at TEXT NOT NULL,
    revoked_at TEXT,
    PRIMARY KEY (workspace_id, actor_id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS offerings (
    offering_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    offering_type TEXT NOT NULL CHECK (offering_type IN ('goods', 'service', 'hybrid')),
    unit_price_idr INTEGER NOT NULL CHECK (unit_price_idr >= 0),
    unit TEXT NOT NULL,
    requires_stock_movement INTEGER NOT NULL CHECK (requires_stock_movement IN (0, 1)),
    valuation_method TEXT,
    tax_status TEXT NOT NULL CHECK (tax_status IN ('not_assessed', 'unknown')),
    tax_reason TEXT NOT NULL,
    tax_amount INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_offerings_workspace
    ON offerings (workspace_id, created_at);

CREATE TABLE IF NOT EXISTS purchases (
    purchase_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    offering_id TEXT NOT NULL,
    qty TEXT NOT NULL,
    total_cost_idr INTEGER NOT NULL CHECK (total_cost_idr >= 0),
    payment_method TEXT NOT NULL DEFAULT 'cash',
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (offering_id) REFERENCES offerings(offering_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS inventory_batches (
    batch_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    offering_id TEXT NOT NULL,
    purchase_id TEXT NOT NULL,
    qty_initial TEXT NOT NULL,
    qty_remaining TEXT NOT NULL,
    total_cost_idr INTEGER NOT NULL CHECK (total_cost_idr >= 0),
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (offering_id) REFERENCES offerings(offering_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_batches_ws_offering
    ON inventory_batches (workspace_id, offering_id);

CREATE TABLE IF NOT EXISTS inventory_pools (
    workspace_id TEXT NOT NULL,
    offering_id TEXT NOT NULL,
    qty_on_hand TEXT NOT NULL,
    total_value_idr INTEGER NOT NULL CHECK (total_value_idr >= 0),
    PRIMARY KEY (workspace_id, offering_id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (offering_id) REFERENCES offerings(offering_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS stock_movements (
    movement_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    offering_id TEXT NOT NULL,
    movement_type TEXT NOT NULL CHECK (movement_type IN ('purchase_in', 'sale_out')),
    qty_delta TEXT NOT NULL,
    unit_cost_idr TEXT,
    total_cost_idr INTEGER,
    reference_type TEXT NOT NULL,
    reference_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sales (
    sale_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    total_revenue_idr INTEGER NOT NULL CHECK (total_revenue_idr >= 0),
    total_cogs_idr INTEGER,
    cogs_status TEXT NOT NULL CHECK (cogs_status IN ('assessed', 'open')),
    policy_version TEXT NOT NULL,
    tax_status TEXT NOT NULL CHECK (tax_status IN ('not_assessed', 'unknown')),
    tax_reason TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sale_lines (
    line_id TEXT PRIMARY KEY,
    sale_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    offering_id TEXT NOT NULL,
    offering_type TEXT NOT NULL,
    qty TEXT NOT NULL,
    revenue_idr INTEGER NOT NULL CHECK (revenue_idr >= 0),
    cogs_idr INTEGER,
    cost_status TEXT NOT NULL CHECK (cost_status IN ('assessed', 'open')),
    FOREIGN KEY (sale_id) REFERENCES sales(sale_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cash_movements (
    cash_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    amount_idr INTEGER NOT NULL CHECK (amount_idr >= 0),
    reference_type TEXT NOT NULL,
    reference_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    workspace_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    response_body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, operation, idempotency_key)
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def is_postgres_dsn(value: str | None) -> bool:
    """Return True when value looks like a PostgreSQL connection URI."""
    if not isinstance(value, str):
        return False
    lower = value.strip().lower()
    return lower.startswith("postgres://") or lower.startswith("postgresql://")


def redact_dsn(target: str) -> str:
    """Mask userinfo and password query parameters from PostgreSQL DSNs for safe logging."""
    if not is_postgres_dsn(target):
        return target
    raw = target.strip()
    try:
        parts = urlsplit(raw)
        host = parts.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = f":{parts.port}" if parts.port is not None else ""
        auth_prefix = "***@" if (parts.username is not None or parts.password is not None) else ""
        netloc = f"{auth_prefix}{host}{port}"
        query_items: list[str] = []
        for key, val in parse_qsl(parts.query, keep_blank_values=True):
            masked_val = "***" if key.lower() in _SENSITIVE_DSN_QUERY_KEYS else val
            enc_key = quote(key, safe="")
            enc_val = quote(masked_val, safe="*._-")
            query_items.append(f"{enc_key}={enc_val}" if val != "" or key.lower() in _SENSITIVE_DSN_QUERY_KEYS else enc_key)
        query = "&".join(query_items)
        return urlunsplit((parts.scheme, netloc, parts.path, query, ""))
    except Exception:
        return "postgresql://***"


def _parse_int_env(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        val = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} harus berupa integer valid.") from exc
    if val < minimum:
        raise ValueError(f"{name} harus >= {minimum}.")
    return val


def _parse_optional_int_env(name: str, *, minimum: int = 1) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        val = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} harus berupa integer valid.") from exc
    if val < minimum:
        raise ValueError(f"{name} harus >= {minimum}.")
    return val


def _parse_auto_migrate_env() -> bool:
    raw = os.environ.get("MARKETSTUDIO_AUTO_MIGRATE", "").strip().lower()
    if raw:
        if raw in ("1", "true", "yes", "on"):
            return True
        if raw in ("0", "false", "no", "off"):
            return False
        raise ValueError("MARKETSTUDIO_AUTO_MIGRATE harus bernilai 0/1 atau true/false.")
    env_mode = os.environ.get("MARKETSTUDIO_ENV", "").strip().lower()
    return env_mode != "production"


@dataclass(frozen=True)
class DatabaseConfig:
    """Resolved backend configuration for SQLite or PostgreSQL."""

    backend: str
    target: str
    sslmode: str | None = None
    connect_timeout: int = 10
    prepare_threshold: int | None = None
    pool_min_size: int = 1
    pool_max_size: int = 10
    statement_timeout_ms: int | None = None
    auto_migrate: bool = True

    @property
    def display_target(self) -> str:
        """Return target path or redacted DSN safe for logs and CLI output."""
        return redact_dsn(self.target)


def resolve_db_config(
    db_path: str | DatabaseConfig | None = None,
    *,
    database_url: str | None = None,
    backend: str | None = None,
) -> DatabaseConfig:
    """Resolve explicit parameters or environment variables into a validated DatabaseConfig."""
    if isinstance(db_path, DatabaseConfig):
        return db_path

    if database_url is not None:
        dsn = database_url.strip()
        if not is_postgres_dsn(dsn):
            raise ValueError("database_url harus menggunakan skema postgres:// atau postgresql://.")
        resolved_backend = "postgres"
        target = dsn
    elif db_path is not None:
        if is_postgres_dsn(db_path):
            resolved_backend = "postgres"
            target = db_path.strip()
        else:
            resolved_backend = "sqlite"
            target = db_path
    else:
        raw_backend = (backend or os.environ.get("MARKETSTUDIO_DB_BACKEND") or "sqlite").strip().lower()
        if raw_backend == "postgresql":
            raw_backend = "postgres"
        if raw_backend not in ("sqlite", "postgres"):
            raise ValueError(f"MARKETSTUDIO_DB_BACKEND '{raw_backend}' tidak didukung (pilih 'sqlite' atau 'postgres').")
        resolved_backend = raw_backend
        if resolved_backend == "sqlite":
            target = os.environ.get("MARKETSTUDIO_DB_PATH") or DEFAULT_DB_PATH
        else:
            dsn = (
                os.environ.get("DATABASE_URL")
                or os.environ.get("MARKETSTUDIO_DATABASE_URL")
                or ""
            ).strip()
            if not dsn:
                raise ValueError("DATABASE_URL wajib diisi saat MARKETSTUDIO_DB_BACKEND=postgres.")
            if not is_postgres_dsn(dsn):
                raise ValueError("DATABASE_URL harus menggunakan skema postgres:// atau postgresql://.")
            target = dsn

    if resolved_backend == "sqlite":
        return DatabaseConfig(backend="sqlite", target=target)

    parsed = urlsplit(target)
    dsn_params = {k.lower(): v for k, v in parse_qsl(parsed.query, keep_blank_values=True)}
    env_sslmode = os.environ.get("MARKETSTUDIO_PG_SSLMODE", "").strip()
    if "sslmode" in dsn_params:
        sslmode: str | None = None
    elif env_sslmode:
        sslmode = env_sslmode
    else:
        host = (parsed.hostname or "").strip().lower()
        sslmode = None if host in _LOCAL_PG_HOSTS else "require"

    connect_timeout = _parse_int_env("MARKETSTUDIO_DB_CONNECT_TIMEOUT", 10, minimum=1)
    pool_min_size = _parse_int_env("MARKETSTUDIO_DB_POOL_MIN", 1, minimum=1)
    pool_max_size = _parse_int_env("MARKETSTUDIO_DB_POOL_MAX", 10, minimum=pool_min_size)

    raw_prep = os.environ.get("MARKETSTUDIO_PG_PREPARE_THRESHOLD", "").strip()
    if not raw_prep or raw_prep.lower() in ("none", "off", "disabled"):
        prepare_threshold: int | None = None
    else:
        try:
            prepare_threshold = int(raw_prep)
        except ValueError as exc:
            raise ValueError("MARKETSTUDIO_PG_PREPARE_THRESHOLD harus integer atau kosong.") from exc
        if prepare_threshold < 0:
            raise ValueError("MARKETSTUDIO_PG_PREPARE_THRESHOLD harus >= 0.")

    statement_timeout_ms = _parse_optional_int_env("MARKETSTUDIO_DB_STATEMENT_TIMEOUT_MS", minimum=1)
    auto_migrate = _parse_auto_migrate_env()

    return DatabaseConfig(
        backend="postgres",
        target=target,
        sslmode=sslmode,
        connect_timeout=connect_timeout,
        prepare_threshold=prepare_threshold,
        pool_min_size=pool_min_size,
        pool_max_size=pool_max_size,
        statement_timeout_ms=statement_timeout_ms,
        auto_migrate=auto_migrate,
    )


def translate_qmark_to_pyformat(sql: str) -> str:
    """Convert SQLite '?' placeholders to PostgreSQL '%s' outside literals, identifiers, and comments."""
    out: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]

        # Single-quoted string literal ('...''...')
        if ch == "'":
            out.append(ch)
            i += 1
            while i < n:
                c = sql[i]
                if c == "%":
                    out.append("%%")
                elif c == "'":
                    out.append("'")
                    if i + 1 < n and sql[i + 1] == "'":
                        out.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                else:
                    out.append(c)
                i += 1
            continue

        # Double-quoted identifier ("...""...")
        if ch == '"':
            out.append(ch)
            i += 1
            while i < n:
                c = sql[i]
                if c == "%":
                    out.append("%%")
                elif c == '"':
                    out.append('"')
                    if i + 1 < n and sql[i + 1] == '"':
                        out.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                else:
                    out.append(c)
                i += 1
            continue

        # Line comment (-- ...\n)
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            out.append("--")
            i += 2
            while i < n:
                c = sql[i]
                out.append("%%" if c == "%" else c)
                i += 1
                if c == "\n":
                    break
            continue

        # Block comment (/* ... */ with PostgreSQL nesting)
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            out.append("/*")
            i += 2
            depth = 1
            while i < n and depth > 0:
                if sql[i] == "/" and i + 1 < n and sql[i + 1] == "*":
                    out.append("/*")
                    depth += 1
                    i += 2
                elif sql[i] == "*" and i + 1 < n and sql[i + 1] == "/":
                    out.append("*/")
                    depth -= 1
                    i += 2
                elif sql[i] == "%":
                    out.append("%%")
                    i += 1
                else:
                    out.append(sql[i])
                    i += 1
            continue

        # Dollar-quoted literal ($tag$...$tag$)
        if ch == "$":
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j < n and sql[j] == "$":
                tag = sql[i : j + 1]
                out.append(tag)
                i = j + 1
                end_idx = sql.find(tag, i)
                if end_idx == -1:
                    out.append(sql[i:].replace("%", "%%"))
                    i = n
                else:
                    out.append(sql[i:end_idx].replace("%", "%%"))
                    out.append(tag)
                    i = end_idx + len(tag)
                continue

        if ch == "?":
            out.append("%s")
        elif ch == "%":
            out.append("%%")
        else:
            out.append(ch)
        i += 1

    return "".join(out)


def _normalize_db_value(value: Any) -> Any:
    """Normalize PostgreSQL native types to match baseline service & JSON contracts."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    if isinstance(value, Decimal):
        if value == 0:
            return "0"
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
    return value


class DbRow:
    """Cross-backend row object supporting dict(row), row['col'], row[idx], and tuple unpacking."""

    __slots__ = ("_columns", "_values", "_index")

    def __init__(self, columns: Sequence[str], values: Sequence[Any]) -> None:
        self._columns = tuple(columns)
        self._values = tuple(_normalize_db_value(v) for v in values)
        self._index = {col: idx for idx, col in enumerate(self._columns)}

    def keys(self) -> tuple[str, ...]:
        return self._columns

    def get(self, key: str, default: Any = None) -> Any:
        idx = self._index.get(key)
        return self._values[idx] if idx is not None else default

    def __getitem__(self, key: str | int | slice) -> Any:
        if isinstance(key, str):
            idx = self._index.get(key)
            if idx is None:
                raise KeyError(key)
            return self._values[idx]
        return self._values[key]

    def __contains__(self, key: object) -> bool:
        if isinstance(key, str):
            return key in self._index
        return False

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __repr__(self) -> str:
        pairs = ", ".join(f"{k}={v!r}" for k, v in zip(self._columns, self._values))
        return f"DbRow({pairs})"


class _BufferedResult:
    """Eager result wrapper so PostgreSQL cursors close immediately inside execute()."""

    __slots__ = ("_rows", "_pos", "rowcount")

    def __init__(self, rows: list[DbRow], rowcount: int) -> None:
        self._rows = rows
        self._pos = 0
        self.rowcount = rowcount

    def fetchone(self) -> DbRow | None:
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row

    def fetchall(self) -> list[DbRow]:
        if self._pos == 0:
            self._pos = len(self._rows)
            return list(self._rows)
        rem = self._rows[self._pos :]
        self._pos = len(self._rows)
        return rem


class _SqliteConnectionAdapter:
    """Thin adapter around sqlite3.Connection matching the cross-backend interface."""

    dialect = "sqlite"

    def __init__(self, raw_conn: sqlite3.Connection) -> None:
        self._conn = raw_conn

    def acquire_write_lock(self, scope_key: str) -> None:  # noqa: ARG002
        # SQLite uses BEGIN IMMEDIATE for serialized write transactions.
        return None

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, tuple(params))

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def _import_psycopg() -> tuple[Any, Any]:
    """Import psycopg and optional psycopg_pool lazily so SQLite mode stays dependency-free."""
    try:
        import psycopg  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "Driver PostgreSQL 'psycopg' belum terpasang. Jalankan `pip install -e '.[postgres]'` "
            "(atau `'.[postgres-binary]'`) untuk memakai backend PostgreSQL."
        ) from exc

    try:
        import psycopg_pool  # type: ignore[import-not-found]
    except ImportError:
        psycopg_pool = None

    return psycopg, psycopg_pool


def build_psycopg_connect_kwargs(config: DatabaseConfig) -> dict[str, Any]:
    """Build keyword arguments for psycopg.connect / ConnectionPool."""
    kwargs: dict[str, Any] = {
        "autocommit": False,
        "connect_timeout": config.connect_timeout,
        "prepare_threshold": config.prepare_threshold,
    }
    if config.sslmode:
        kwargs["sslmode"] = config.sslmode
    return kwargs


def _connect_postgres_raw(config: DatabaseConfig) -> Any:
    psycopg, _ = _import_psycopg()
    kwargs = build_psycopg_connect_kwargs(config)
    try:
        return psycopg.connect(config.target, **kwargs)
    except psycopg.OperationalError as exc:
        raise DomainError(503, "database_unavailable", "Layanan database tidak tersedia sementara.") from exc


class PostgresPoolManager:
    """Managed psycopg_pool.ConnectionPool wrapper for PostgreSQL runtime servers."""

    def __init__(self, config: DatabaseConfig) -> None:
        psycopg, psycopg_pool = _import_psycopg()
        if psycopg_pool is None:
            raise RuntimeError(
                "Package 'psycopg_pool' belum terpasang. Pasang `psycopg[pool]` untuk connection pooling."
            )
        self.config = config
        self._psycopg = psycopg
        self._pool_timeout_exc = psycopg_pool.PoolTimeout
        self._pool = psycopg_pool.ConnectionPool(
            conninfo=config.target,
            min_size=config.pool_min_size,
            max_size=config.pool_max_size,
            timeout=float(config.connect_timeout),
            kwargs=build_psycopg_connect_kwargs(config),
            open=True,
        )

    @contextmanager
    def connection(self) -> Iterator[Any]:
        try:
            with self._pool.connection() as conn:
                yield conn
        except (self._psycopg.OperationalError, self._pool_timeout_exc) as exc:
            raise DomainError(503, "database_unavailable", "Layanan database tidak tersedia sementara.") from exc

    def close(self) -> None:
        self._pool.close()


class _PostgresConnectionAdapter:
    """Adapter around psycopg.Connection exposing SQLite-compatible execute() and DbRow."""

    dialect = "postgres"

    def __init__(self, raw_conn: Any) -> None:
        self._conn = raw_conn

    def acquire_write_lock(self, scope_key: str) -> None:
        # Transaction-scoped advisory lock is safe under Supavisor/PgBouncer transaction pooling
        # and prevents concurrent write anomalies on the same tenant/principal under READ COMMITTED.
        with self._conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (scope_key,))

    def execute(self, sql: str, params: Sequence[Any] = ()) -> _BufferedResult:
        with self._conn.cursor() as cur:
            if params:
                pg_sql = translate_qmark_to_pyformat(sql)
                cur.execute(pg_sql, tuple(params))
            else:
                cur.execute(sql)
            if cur.description is None:
                return _BufferedResult([], cur.rowcount)
            columns = tuple(desc.name for desc in cur.description)
            raw_rows = cur.fetchall()
            rows = [DbRow(columns, r) for r in raw_rows]
            return _BufferedResult(rows, cur.rowcount)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()


def _init_sqlite_db(db_path: str) -> str:
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path, timeout=10.0)) as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA_SQL)
        ws_cols = {r["name"] for r in conn.execute("PRAGMA table_info(workspaces)").fetchall()}
        if "is_demo" not in ws_cols:
            conn.execute("ALTER TABLE workspaces ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0")
        if "demo_slug" not in ws_cols:
            conn.execute("ALTER TABLE workspaces ADD COLUMN demo_slug TEXT")
        rows = conn.execute(
            "SELECT workspace_id, offering_id, movement_type, qty_delta, total_cost_idr FROM stock_movements"
        ).fetchall()
        pools: dict[tuple[str, str], list[Any]] = {}
        for r in rows:
            key = (r["workspace_id"], r["offering_id"])
            if key not in pools:
                pools[key] = [Decimal("0"), 0]
            pools[key][0] += Decimal(r["qty_delta"])
            cost = int(r["total_cost_idr"] or 0)
            pools[key][1] += cost if r["movement_type"] == "purchase_in" else -cost
        for (ws_id, off_id), (qty, val) in pools.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO inventory_pools (workspace_id, offering_id, qty_on_hand, total_value_idr)
                VALUES (?, ?, ?, ?)
                """,
                (ws_id, off_id, str(qty.normalize() if qty != 0 else Decimal("0")), val),
            )
        conn.commit()
    return db_path


def init_db(
    db_path: str | DatabaseConfig | None = None,
    *,
    database_url: str | None = None,
    backend: str | None = None,
    auto_migrate: bool | None = None,
) -> str:
    """Initialize SQLite schema or verify/apply versioned PostgreSQL migrations."""
    config = resolve_db_config(db_path=db_path, database_url=database_url, backend=backend)
    if config.backend == "sqlite":
        return _init_sqlite_db(config.target)

    from app.migrations import MigrationError, apply_migrations, verify_migrations_current

    should_auto_migrate = config.auto_migrate if auto_migrate is None else auto_migrate
    raw_conn = _connect_postgres_raw(config)
    try:
        is_current, pending, _ = verify_migrations_current(raw_conn)
        raw_conn.commit()
    except Exception:
        if not raw_conn.closed:
            raw_conn.rollback()
        raise
    finally:
        raw_conn.close()

    if is_current:
        return config.display_target

    if should_auto_migrate:
        apply_migrations(config.target)
        return config.display_target

    raise MigrationError(
        f"Pending PostgreSQL migrations ({', '.join(pending)}). "
        "Jalankan `python3 -m app.migrations up` dengan role migrator terlebih dahulu."
    )


@contextmanager
def db_transaction(
    db_path: str | DatabaseConfig | None = None,
    immediate: bool = False,
    *,
    database_url: str | None = None,
    backend: str | None = None,
    pool: PostgresPoolManager | None = None,
) -> Iterator[_SqliteConnectionAdapter | _PostgresConnectionAdapter]:
    """Yield a connection inside an atomic transaction on either SQLite or PostgreSQL."""
    config = resolve_db_config(db_path=db_path, database_url=database_url, backend=backend)

    if config.backend == "sqlite":
        conn = sqlite3.connect(config.target, timeout=15.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        adapter = _SqliteConnectionAdapter(conn)
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("BEGIN IMMEDIATE;" if immediate else "BEGIN;")
            yield adapter
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return

    if pool is not None:
        with pool.connection() as pg_conn:
            try:
                if config.statement_timeout_ms is not None:
                    with pg_conn.cursor() as cur:
                        cur.execute(
                            "SELECT set_config('statement_timeout', %s, true)",
                            (str(config.statement_timeout_ms),),
                        )
                yield _PostgresConnectionAdapter(pg_conn)
                pg_conn.commit()
            except Exception:
                if not pg_conn.closed:
                    pg_conn.rollback()
                raise
        return

    pg_conn = _connect_postgres_raw(config)
    try:
        if config.statement_timeout_ms is not None:
            with pg_conn.cursor() as cur:
                cur.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(config.statement_timeout_ms),),
                )
        yield _PostgresConnectionAdapter(pg_conn)
        pg_conn.commit()
    except Exception:
        if not pg_conn.closed:
            pg_conn.rollback()
        raise
    finally:
        pg_conn.close()
