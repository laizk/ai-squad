DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'run_status') THEN
    CREATE TYPE run_status AS ENUM ('created', 'running', 'paused', 'completed', 'failed', 'cancelled');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'run_step_status') THEN
    CREATE TYPE run_step_status AS ENUM ('pending', 'running', 'completed', 'failed', 'skipped');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'artifact_type') THEN
    CREATE TYPE artifact_type AS ENUM (
      'spec', 'milestone_plan', 'tasks', 'acceptance_criteria',
      'ui_notes', 'component_map', 'ux_risks',
      'implementation_summary', 'code_diff',
      'review_findings', 'refactor_summary',
      'test_plan', 'test_results', 'bug_list',
      'docker_changes', 'ci_changes', 'runbook',
      'rubric_score', 'recommendation', 'other'
    );
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS runs (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id        UUID NOT NULL REFERENCES projects(id),
  task_id           UUID REFERENCES tasks(id),
  status            run_status NOT NULL DEFAULT 'created',
  workflow_type     VARCHAR(100) NOT NULL DEFAULT 'pm_planning',
  trigger_actor     VARCHAR(255) NOT NULL DEFAULT 'human:local',
  idempotency_key   VARCHAR(255) NOT NULL UNIQUE,
  started_at        TIMESTAMPTZ,
  paused_at         TIMESTAMPTZ,
  completed_at      TIMESTAMPTZ,
  error_message     TEXT,
  metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS run_steps (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  run_id            UUID NOT NULL REFERENCES runs(id),
  role              team_member_role NOT NULL,
  step_order        INTEGER NOT NULL,
  status            run_step_status NOT NULL DEFAULT 'pending',
  pause_after       BOOLEAN NOT NULL DEFAULT FALSE,
  output_artifact_id UUID,
  started_at        TIMESTAMPTZ,
  completed_at      TIMESTAMPTZ,
  error_message     TEXT,
  metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (run_id, step_order)
);

CREATE TABLE IF NOT EXISTS artifacts (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id        UUID NOT NULL REFERENCES projects(id),
  run_id            UUID REFERENCES runs(id),
  run_step_id       UUID REFERENCES run_steps(id),
  role              team_member_role,
  artifact_type     artifact_type NOT NULL,
  name              VARCHAR(255) NOT NULL,
  body              TEXT NOT NULL DEFAULT '',
  version           INTEGER NOT NULL DEFAULT 1,
  is_current        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Deferred FK: run_steps.output_artifact_id → artifacts.id
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_run_steps_output_artifact'
  ) THEN
    ALTER TABLE run_steps
      ADD CONSTRAINT fk_run_steps_output_artifact
      FOREIGN KEY (output_artifact_id) REFERENCES artifacts(id);
  END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_runs_project   ON runs(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status    ON runs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_steps_run  ON run_steps(run_id, step_order ASC);
CREATE INDEX IF NOT EXISTS idx_artifacts_run  ON artifacts(run_id, created_at DESC);

GRANT SELECT, INSERT, UPDATE ON runs       TO squad_app;
GRANT SELECT, INSERT, UPDATE ON run_steps  TO squad_app;
GRANT SELECT, INSERT, UPDATE ON artifacts  TO squad_app;
