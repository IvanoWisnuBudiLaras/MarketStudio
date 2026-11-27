-- Rollback Migration 0001: Drop initial MarketStudio PostgreSQL tables in reverse dependency order.

DROP TABLE IF EXISTS audit_events;
DROP TABLE IF EXISTS idempotency_keys;
DROP TABLE IF EXISTS cash_movements;
DROP TABLE IF EXISTS sale_lines;
DROP TABLE IF EXISTS sales;
DROP TABLE IF EXISTS stock_movements;
DROP TABLE IF EXISTS inventory_pools;
DROP TABLE IF EXISTS inventory_batches;
DROP TABLE IF EXISTS purchases;
DROP TABLE IF EXISTS offerings;
DROP TABLE IF EXISTS workspace_memberships;
DROP TABLE IF EXISTS workspaces;
DROP TABLE IF EXISTS sessions;
