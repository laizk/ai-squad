-- P7: webhook event store (append-only) and GitHub ref columns on runs/run_steps.
--
-- webhook_events is intentionally append-only: no UPDATE or DELETE grants.
-- The app role may INSERT and SELECT only.

DO $$
BEGIN
  -- Append-only webhook event log
  IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'webhook_events') THEN
    CREATE TABLE webhook_events (
      id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
      source        VARCHAR(50)  NOT NULL DEFAULT 'github',
      event_type    VARCHAR(100) NOT NULL,           -- X-GitHub-Event header value
      delivery_id   VARCHAR(255),                    -- X-GitHub-Delivery header value
      payload       JSONB        NOT NULL,
      raw_headers   JSONB        NOT NULL DEFAULT '{}'::jsonb,
      received_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    );
    -- Lookup by delivery_id (idempotent replay checks)
    CREATE INDEX IF NOT EXISTS webhook_events_delivery_id_idx
      ON webhook_events (delivery_id)
      WHERE delivery_id IS NOT NULL;
    -- Lookup by event_type for reconciler queries
    CREATE INDEX IF NOT EXISTS webhook_events_event_type_idx
      ON webhook_events (event_type, received_at DESC);
  END IF;

  -- GitHub ref tracking on runs
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_name = 'runs' AND column_name = 'github_issue_number'
  ) THEN
    ALTER TABLE runs
      ADD COLUMN github_issue_number INTEGER,
      ADD COLUMN github_branch        VARCHAR(255),
      ADD COLUMN github_pr_number     INTEGER;
  END IF;
END
$$;

-- Grant INSERT + SELECT on webhook_events to the app role.
-- No UPDATE or DELETE — this table is append-only by policy.
DO $$
DECLARE
  app_role TEXT := current_setting('app.db_role', true);
BEGIN
  IF app_role IS NULL OR app_role = '' THEN
    app_role := 'squad_app';
  END IF;
  EXECUTE format('GRANT SELECT, INSERT ON webhook_events TO %I', app_role);
END
$$;
