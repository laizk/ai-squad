-- AI Squad Postgres init script
-- This runs on first container start before application migrations.
--
-- Purpose:
-- 1. create the restricted application role used by control-api
-- 2. reserve the database owner role for schema management only

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'squad_app') THEN
    CREATE ROLE squad_app LOGIN PASSWORD 'squadapp-local';
  END IF;
END
$$;

GRANT CONNECT ON DATABASE squad TO squad_app;
GRANT USAGE ON SCHEMA public TO squad_app;

-- Table privileges are granted again after migrations by the migration/bootstrap step.
-- The app role should never own schema objects and should never receive DDL privileges.

SELECT 'AI Squad database initialized with restricted app role' AS status;
