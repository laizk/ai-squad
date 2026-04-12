-- P9: prompt evaluation run store.
--
-- Each eval run records:
--   - the team member being evaluated
--   - the revision number of their prompt/config under test
--   - the golden task used as input
--   - the raw output artifact produced
--   - scores (structure defined by the eval scorer)
--   - status and timestamps
--
-- Status transitions: pending → running → completed | failed
-- Rows are never deleted; UPDATE is permitted for status transitions.

-- 1. ENUM type (idempotent)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'eval_status') THEN
    CREATE TYPE eval_status AS ENUM ('pending', 'running', 'completed', 'failed');
  END IF;
END
$$;

-- 2. Table (idempotent)
CREATE TABLE IF NOT EXISTS prompt_eval_runs (
  id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  team_member_id      UUID NOT NULL REFERENCES team_members(id),
  revision_number     INTEGER NOT NULL,
  golden_task_key     VARCHAR(255) NOT NULL,
  status              eval_status NOT NULL DEFAULT 'pending',
  output_artifact     JSONB,          -- raw agent output stored inline
  scores              JSONB,          -- {overall: int, dimensions: [...], pass: bool}
  error_message       TEXT,
  started_at          TIMESTAMPTZ,
  completed_at        TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Index (idempotent)
CREATE INDEX IF NOT EXISTS prompt_eval_runs_member_task_idx
  ON prompt_eval_runs (team_member_id, golden_task_key, revision_number DESC);

-- 4. Delete-protection trigger (function created once, trigger idempotent)
CREATE OR REPLACE FUNCTION forbid_eval_delete()
  RETURNS TRIGGER LANGUAGE plpgsql AS $func$
BEGIN
  RAISE EXCEPTION 'prompt_eval_runs rows may not be deleted';
END;
$func$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_eval_no_delete'
  ) THEN
    CREATE TRIGGER trg_eval_no_delete
      BEFORE DELETE ON prompt_eval_runs
      FOR EACH ROW EXECUTE FUNCTION forbid_eval_delete();
  END IF;
END
$$;

-- 5. Grants
DO $$
DECLARE app_role TEXT := 'squad_app';
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = app_role) THEN
    EXECUTE format('GRANT SELECT, INSERT, UPDATE ON prompt_eval_runs TO %I', app_role);
  END IF;
END
$$;
