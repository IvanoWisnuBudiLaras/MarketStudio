-- MarketStudio PostgreSQL / Supabase Migration 0002
-- Enable default-deny Row Level Security on all tables and restrict PUBLIC/anon/authenticated access,
-- while granting DML-only privileges to service_role (if present).

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
        EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', target_schema, tbl);
        EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM PUBLIC', target_schema, tbl);

        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM anon', target_schema, tbl);
        END IF;

        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM authenticated', target_schema, tbl);
        END IF;

        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM service_role', target_schema, tbl);
            EXECUTE format(
                'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I.%I TO service_role',
                target_schema,
                tbl
            );
        END IF;
    END LOOP;

    IF to_regclass(format('%I.schema_migrations', target_schema)) IS NOT NULL THEN
        EXECUTE format('ALTER TABLE %I.schema_migrations ENABLE ROW LEVEL SECURITY', target_schema);
        EXECUTE format('REVOKE ALL ON TABLE %I.schema_migrations FROM PUBLIC', target_schema);

        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            EXECUTE format('REVOKE ALL ON TABLE %I.schema_migrations FROM anon', target_schema);
        END IF;

        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            EXECUTE format('REVOKE ALL ON TABLE %I.schema_migrations FROM authenticated', target_schema);
        END IF;

        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            EXECUTE format('REVOKE ALL ON TABLE %I.schema_migrations FROM service_role', target_schema);
            EXECUTE format('GRANT SELECT ON TABLE %I.schema_migrations TO service_role', target_schema);
        END IF;
    END IF;
END
$$;
