CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'project_status') THEN
    CREATE TYPE project_status AS ENUM ('active', 'paused', 'archived');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'team_member_role') THEN
    CREATE TYPE team_member_role AS ENUM ('pm', 'ux', 'dev-jr', 'dev-sr', 'qa', 'devops', 'judge', 'custom');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'provider_type') THEN
    CREATE TYPE provider_type AS ENUM ('ollama', 'anthropic', 'openai', 'custom');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'milestone_status') THEN
    CREATE TYPE milestone_status AS ENUM ('planned', 'in_progress', 'review', 'pending_approval', 'approved', 'rejected');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'task_status') THEN
    CREATE TYPE task_status AS ENUM (
      'backlog', 'queued', 'in_progress', 'review', 'qa_check',
      'judge_review', 'pending_human', 'done', 'rejected', 'rework'
    );
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'task_priority') THEN
    CREATE TYPE task_priority AS ENUM ('low', 'medium', 'high', 'critical');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'entity_type') THEN
    CREATE TYPE entity_type AS ENUM ('project', 'team_member', 'project_assignment', 'milestone', 'task');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'reason_category') THEN
    CREATE TYPE reason_category AS ENUM (
      'initial_creation', 'scope_change', 'prompt_tuning', 'fix',
      'rollback', 'human_override', 'policy_change', 'retry', 'other'
    );
  END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO squad_app;

CREATE TABLE IF NOT EXISTS projects (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name              VARCHAR(255) NOT NULL,
  description       TEXT,
  status            project_status NOT NULL DEFAULT 'active',
  github_org        VARCHAR(255),
  github_repo       VARCHAR(255),
  github_project_id VARCHAR(255),
  current_version   INTEGER NOT NULL DEFAULT 1,
  metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS team_members (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name              VARCHAR(255) NOT NULL,
  role              team_member_role NOT NULL,
  display_name      VARCHAR(255) NOT NULL,
  description       TEXT,
  skills            TEXT[] NOT NULL DEFAULT '{}',
  provider          provider_type NOT NULL DEFAULT 'ollama',
  model             VARCHAR(255) NOT NULL DEFAULT 'unassigned',
  current_version   INTEGER NOT NULL DEFAULT 1,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS project_team_members (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id        UUID NOT NULL REFERENCES projects(id),
  team_member_id    UUID NOT NULL REFERENCES team_members(id),
  is_enabled        BOOLEAN NOT NULL DEFAULT TRUE,
  provider_override provider_type,
  model_override    VARCHAR(255),
  disabled_at       TIMESTAMPTZ,
  disable_reason    TEXT,
  current_version   INTEGER NOT NULL DEFAULT 1,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (project_id, team_member_id)
);

CREATE TABLE IF NOT EXISTS milestones (
  id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id          UUID NOT NULL REFERENCES projects(id),
  title               VARCHAR(500) NOT NULL,
  description         TEXT,
  status              milestone_status NOT NULL DEFAULT 'planned',
  display_order       INTEGER NOT NULL DEFAULT 0,
  acceptance_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
  due_date            DATE,
  current_version     INTEGER NOT NULL DEFAULT 1,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tasks (
  id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id          UUID NOT NULL REFERENCES projects(id),
  milestone_id        UUID NOT NULL REFERENCES milestones(id),
  title               VARCHAR(500) NOT NULL,
  description         TEXT,
  status              task_status NOT NULL DEFAULT 'backlog',
  priority            task_priority NOT NULL DEFAULT 'medium',
  assigned_role       team_member_role,
  acceptance_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
  display_order       INTEGER NOT NULL DEFAULT 0,
  current_version     INTEGER NOT NULL DEFAULT 1,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS revisions (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  entity_type       entity_type NOT NULL,
  entity_id         UUID NOT NULL,
  revision_number   INTEGER NOT NULL,
  actor             VARCHAR(255) NOT NULL,
  change_summary    TEXT NOT NULL,
  reason_category   reason_category NOT NULL,
  reason_detail     TEXT NOT NULL,
  reason_references JSONB NOT NULL DEFAULT '[]'::jsonb,
  before_snapshot   JSONB,
  after_snapshot    JSONB NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (entity_type, entity_id, revision_number)
);

CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_milestones_project ON milestones(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_milestone ON tasks(milestone_id);
CREATE INDEX IF NOT EXISTS idx_revisions_lookup ON revisions(entity_type, entity_id, revision_number DESC);

CREATE OR REPLACE FUNCTION forbid_revision_mutation()
RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION 'revisions table is append-only';
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_trigger
    WHERE tgname = 'trg_revisions_no_update'
  ) THEN
    CREATE TRIGGER trg_revisions_no_update
    BEFORE UPDATE ON revisions
    FOR EACH ROW EXECUTE FUNCTION forbid_revision_mutation();
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_trigger
    WHERE tgname = 'trg_revisions_no_delete'
  ) THEN
    CREATE TRIGGER trg_revisions_no_delete
    BEFORE DELETE ON revisions
    FOR EACH ROW EXECUTE FUNCTION forbid_revision_mutation();
  END IF;
END
$$;

GRANT SELECT, INSERT, UPDATE ON projects TO squad_app;
GRANT SELECT, INSERT ON revisions TO squad_app;
GRANT SELECT ON team_members TO squad_app;
GRANT SELECT ON project_team_members TO squad_app;
GRANT SELECT ON milestones TO squad_app;
GRANT SELECT ON tasks TO squad_app;
