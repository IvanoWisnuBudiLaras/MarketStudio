ALTER TABLE offerings ADD COLUMN IF NOT EXISTS service_cost_idr BIGINT CHECK (service_cost_idr IS NULL OR (service_cost_idr >= 0 AND service_cost_idr <= 1000000000000000));
ALTER TABLE offerings ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE offerings ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS pricing_decisions (
    decision_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    offering_id TEXT NOT NULL REFERENCES offerings(offering_id) ON DELETE CASCADE,
    previous_price_idr BIGINT NOT NULL CHECK (previous_price_idr >= 0 AND previous_price_idr <= 1000000000000000),
    new_price_idr BIGINT NOT NULL CHECK (new_price_idr >= 0 AND new_price_idr <= 1000000000000000),
    unit_cost_idr BIGINT CHECK (unit_cost_idr IS NULL OR (unit_cost_idr >= 0 AND unit_cost_idr <= 1000000000000000)),
    cost_status TEXT NOT NULL CHECK (cost_status IN ('known', 'unknown')),
    margin_idr BIGINT,
    margin_pct NUMERIC(6, 2),
    strategy_notes TEXT NOT NULL DEFAULT '',
    actor_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pricing_decisions_offering
    ON pricing_decisions (workspace_id, offering_id, created_at);

ALTER TABLE pricing_decisions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE pricing_decisions FROM PUBLIC;
