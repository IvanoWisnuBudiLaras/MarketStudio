-- MarketStudio PostgreSQL / Supabase Initial Schema (Migration 0001)
-- Additive and idempotent for PostgreSQL 17 / Supabase public schema.
-- Preserves exact integer IDR bounds (BIGINT <= 10^15), exact NUMERIC quantities/costs,
-- TIMESTAMPTZ timestamps, and boolean stock movement flags.

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    actor_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    business_type TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'IDR',
    timezone TEXT NOT NULL DEFAULT 'Asia/Jakarta',
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    demo_slug TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS workspace_memberships (
    workspace_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'owner',
    created_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    PRIMARY KEY (workspace_id, actor_id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS offerings (
    offering_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    offering_type TEXT NOT NULL CHECK (offering_type IN ('goods', 'service', 'hybrid')),
    unit_price_idr BIGINT NOT NULL CHECK (unit_price_idr >= 0 AND unit_price_idr <= 1000000000000000),
    unit TEXT NOT NULL,
    requires_stock_movement BOOLEAN NOT NULL,
    valuation_method TEXT,
    tax_status TEXT NOT NULL CHECK (tax_status IN ('not_assessed', 'unknown')),
    tax_reason TEXT NOT NULL,
    tax_amount BIGINT CHECK (tax_amount IS NULL),
    created_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_offerings_workspace
    ON offerings (workspace_id, created_at);

CREATE TABLE IF NOT EXISTS purchases (
    purchase_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    offering_id TEXT NOT NULL,
    qty NUMERIC NOT NULL CHECK (qty > 0),
    total_cost_idr BIGINT NOT NULL CHECK (total_cost_idr >= 0 AND total_cost_idr <= 1000000000000000),
    payment_method TEXT NOT NULL DEFAULT 'cash',
    occurred_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (offering_id) REFERENCES offerings(offering_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_purchases_ws_occurred
    ON purchases (workspace_id, occurred_at);

CREATE TABLE IF NOT EXISTS inventory_batches (
    batch_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    offering_id TEXT NOT NULL,
    purchase_id TEXT NOT NULL,
    qty_initial NUMERIC NOT NULL CHECK (qty_initial > 0),
    qty_remaining NUMERIC NOT NULL CHECK (qty_remaining >= 0),
    total_cost_idr BIGINT NOT NULL CHECK (total_cost_idr >= 0 AND total_cost_idr <= 1000000000000000),
    occurred_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (offering_id) REFERENCES offerings(offering_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_batches_ws_offering
    ON inventory_batches (workspace_id, offering_id, occurred_at, batch_id);

CREATE TABLE IF NOT EXISTS inventory_pools (
    workspace_id TEXT NOT NULL,
    offering_id TEXT NOT NULL,
    qty_on_hand NUMERIC NOT NULL CHECK (qty_on_hand >= 0),
    total_value_idr BIGINT NOT NULL CHECK (total_value_idr >= 0 AND total_value_idr <= 1000000000000000),
    PRIMARY KEY (workspace_id, offering_id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (offering_id) REFERENCES offerings(offering_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS stock_movements (
    movement_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    offering_id TEXT NOT NULL,
    movement_type TEXT NOT NULL CHECK (movement_type IN ('purchase_in', 'sale_out')),
    qty_delta NUMERIC NOT NULL CHECK (qty_delta <> 0),
    unit_cost_idr NUMERIC,
    total_cost_idr BIGINT CHECK (total_cost_idr IS NULL OR (total_cost_idr >= 0 AND total_cost_idr <= 1000000000000000)),
    reference_type TEXT NOT NULL,
    reference_id TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_stock_movements_ws_off_occurred
    ON stock_movements (workspace_id, offering_id, occurred_at);

CREATE INDEX IF NOT EXISTS idx_stock_movements_ws_occurred
    ON stock_movements (workspace_id, occurred_at);

CREATE TABLE IF NOT EXISTS sales (
    sale_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    total_revenue_idr BIGINT NOT NULL CHECK (total_revenue_idr >= 0 AND total_revenue_idr <= 1000000000000000),
    total_cogs_idr BIGINT,
    cogs_status TEXT NOT NULL CHECK (cogs_status IN ('assessed', 'open')),
    policy_version TEXT NOT NULL,
    tax_status TEXT NOT NULL CHECK (tax_status IN ('not_assessed', 'unknown')),
    tax_reason TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    CHECK (
        (cogs_status = 'open' AND total_cogs_idr IS NULL)
        OR (
            cogs_status = 'assessed'
            AND total_cogs_idr IS NOT NULL
            AND total_cogs_idr >= 0
            AND total_cogs_idr <= 1000000000000000
        )
    ),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sales_ws_occurred
    ON sales (workspace_id, occurred_at);

CREATE TABLE IF NOT EXISTS sale_lines (
    line_id TEXT PRIMARY KEY,
    sale_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    offering_id TEXT NOT NULL,
    offering_type TEXT NOT NULL,
    qty NUMERIC NOT NULL CHECK (qty > 0),
    revenue_idr BIGINT NOT NULL CHECK (revenue_idr >= 0 AND revenue_idr <= 1000000000000000),
    cogs_idr BIGINT,
    cost_status TEXT NOT NULL CHECK (cost_status IN ('assessed', 'open')),
    CHECK (
        (cost_status = 'open' AND cogs_idr IS NULL)
        OR (
            cost_status = 'assessed'
            AND cogs_idr IS NOT NULL
            AND cogs_idr >= 0
            AND cogs_idr <= 1000000000000000
        )
    ),
    FOREIGN KEY (sale_id) REFERENCES sales(sale_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sale_lines_sale_id
    ON sale_lines (sale_id);

CREATE INDEX IF NOT EXISTS idx_sale_lines_ws
    ON sale_lines (workspace_id);

CREATE TABLE IF NOT EXISTS cash_movements (
    cash_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    amount_idr BIGINT NOT NULL CHECK (amount_idr >= 0 AND amount_idr <= 1000000000000000),
    reference_type TEXT NOT NULL,
    reference_id TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cash_movements_ws_occurred
    ON cash_movements (workspace_id, occurred_at);

-- Note: create_workspace stores 'principal:<actor>' in workspace_id, so no FK to workspaces here.
CREATE TABLE IF NOT EXISTS idempotency_keys (
    workspace_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    response_body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (workspace_id, operation, idempotency_key)
);

-- Append-only logical audit trail; intentionally has no FK cascade from workspaces.
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_events_ws_created
    ON audit_events (workspace_id, created_at DESC);
