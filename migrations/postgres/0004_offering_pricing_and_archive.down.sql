DROP TABLE IF EXISTS pricing_decisions;
ALTER TABLE offerings DROP COLUMN IF EXISTS archived_at;
ALTER TABLE offerings DROP COLUMN IF EXISTS is_archived;
ALTER TABLE offerings DROP COLUMN IF EXISTS service_cost_idr;
