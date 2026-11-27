-- Rollback Migration 0002: Disable RLS and revoke service_role table grants added in 0002.

DO $$
DECLARE
    target_schema TEXT := current_schema();
    domain_tables TEXT[] := ARRAY[
        'sessions',
        'workspaces',
        'workspace_memberships',
        'offerings',
        'purchases',
        'inventory_batches',
        'inventory_pools',
        'stock_movements',
        'sales',
        'sale_lines',
        'cash_movements',
        'idempotency_keys',
        'audit_events'
    ];
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY domain_tables LOOP
        IF to_regclass(format('%I.%I', target_schema, tbl)) IS NOT NULL THEN
            EXECUTE format('ALTER TABLE %I.%I DISABLE ROW LEVEL SECURITY', target_schema, tbl);
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
                EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM service_role', target_schema, tbl);
            END IF;
        END IF;
    END LOOP;

    IF to_regclass(format('%I.schema_migrations', target_schema)) IS NOT NULL THEN
        EXECUTE format('ALTER TABLE %I.schema_migrations DISABLE ROW LEVEL SECURITY', target_schema);
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            EXECUTE format('REVOKE ALL ON TABLE %I.schema_migrations FROM service_role', target_schema);
        END IF;
    END IF;
END
$$;
