"""SQLite persistence layer for MarketStudio baseline."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator

DEFAULT_DB_PATH = os.environ.get(
    "MARKETSTUDIO_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "marketstudio.db"),
)

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


def init_db(db_path: str = DEFAULT_DB_PATH) -> str:
    """Initialize SQLite database and apply schema idempotently."""
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path, timeout=10.0)) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    return db_path


@contextmanager
def db_transaction(db_path: str = DEFAULT_DB_PATH, immediate: bool = False) -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection inside an atomic transaction."""
    conn = sqlite3.connect(db_path, timeout=15.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("BEGIN IMMEDIATE;" if immediate else "BEGIN;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
