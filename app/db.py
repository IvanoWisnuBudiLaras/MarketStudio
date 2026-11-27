"""SQLite persistence layer for MarketStudio baseline."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DEFAULT_DB_PATH = os.environ.get(
    "MARKETSTUDIO_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "marketstudio.db"),
)

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    business_type TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'IDR',
    timezone TEXT NOT NULL DEFAULT 'Asia/Jakarta',
    created_at TEXT NOT NULL
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


def init_db(db_path: str = DEFAULT_DB_PATH) -> str:
    """Initialize SQLite database and apply schema idempotently."""
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    return db_path


@contextmanager
def db_transaction(db_path: str = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection inside an atomic transaction."""
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
