-- AI Squad Platform Schema
-- Version: 0.2.0-architecture-refresh
-- Date: 2026-04-11
--
-- Notes:
-- 1. This is the intended baseline schema for the revised architecture.
-- 2. Revisions are append-only by application behavior, privilege, and trigger.
-- 3. Large prompt and document bodies are deduplicated in content_blobs.
-- 4. Approvals are revision-bound and become stale after later edits.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- ENUMS
-- ============================================================

CREATE TYPE project_status AS ENUM ('active', 'paused', 'archived');
CREATE TYPE team_member_role AS ENUM ('pm', 'ux', 'dev-jr', 'dev-sr', 'qa', 'devops', 'judge', 'custom');
CREATE TYPE provider_type AS ENUM ('ollama', 'anthropic', 'openai', 'custom');
CREATE TYPE milestone_status AS ENUM ('planned', 'in_progress', 'review', 'pending_approval', 'approved', 'rejected');
CREATE TYPE task_status AS ENUM (
  'backlog', 'queued', 'in_progress', 'review', 'qa_check',
  'judge_review', 'pending_human', 'done', 'rejected', 'rework'
);
CREATE TYPE task_priority AS ENUM ('low', 'medium', 'high', 'critical');
CREATE TYPE run_status AS ENUM ('created', 'running', 'paused', 'completed', 'failed', 'cancelled');
CREATE TYPE run_step_status AS ENUM ('pending', 'running', 'completed', 'failed', 'skipped');
CREATE TYPE approval_status AS ENUM ('pending', 'approved', 'rejected', 'changes_requested');
CREATE TYPE entity_type AS ENUM (
  'project', 'team_member', 'project_assignment', 'milestone', 'task',
  'artifact', 'role_policy', 'prompt_eval', 'run', 'approval'
);
CREATE TYPE artifact_type AS ENUM (
  'spec', 'milestone_plan', 'tasks', 'acceptance_criteria',
  'ui_notes', 'component_map', 'ux_risks',
  'implementation_summary', 'code_diff',
  'review_findings', 'refactor_summary',
  'test_plan', 'test_results', 'bug_list',
  'docker_changes', 'ci_changes', 'runbook',
  'rubric_score', 'recommendation', 'other'
);
CREATE TYPE reason_category AS ENUM (
  'initial_creation', 'scope_change', 'prompt_tuning', 'fix',
  'rollback', 'human_override', 'policy_change', 'retry', 'other'
);
CREATE TYPE evidence_type AS ENUM ('artifact', 'test_result', 'screenshot', 'log', 'github_link', 'other');
CREATE TYPE decision_type AS ENUM (
  'task_breakdown', 'code_approach', 'test_strategy',
  'review_finding', 'score', 'recommendation', 'other'
);
CREATE TYPE violation_type AS ENUM (
  'permission_denied', 'secrets_detected', 'sandbox_timeout',
  'sandbox_escape_attempt', 'force_push_attempt',
  'out_of_scope_action', 'contract_violation', 'network_egress_attempt'
);

-- ============================================================
-- CONTENT BLOBS
-- ============================================================

CREATE TABLE content_blobs (
  content_hash     VARCHAR(64) PRIMARY KEY,
  content          TEXT NOT NULL,
  size_bytes       INTEGER NOT NULL,
  ref_count        INTEGER NOT NULL DEFAULT 0,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- CORE PROJECT TABLES
-- ============================================================

CREATE TABLE projects (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name             VARCHAR(255) NOT NULL,
  description      TEXT,
  status           project_status NOT NULL DEFAULT 'active',
  github_org       VARCHAR(255),
  github_repo      VARCHAR(255),
  github_project_id VARCHAR(255),
  current_version  INTEGER NOT NULL DEFAULT 1,
  metadata         JSONB NOT NULL DEFAULT '{}',
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE role_github_policies (
  role                    team_member_role PRIMARY KEY,
  allowed_actions         TEXT[] NOT NULL DEFAULT '{}',
  allowed_branch_patterns TEXT[] NOT NULL DEFAULT '{}',
  max_issues_per_run      INTEGER NOT NULL DEFAULT 20,
  max_comments_per_run    INTEGER NOT NULL DEFAULT 10,
  current_version         INTEGER NOT NULL DEFAULT 1,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE team_members (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name             VARCHAR(255) NOT NULL,
  role             team_member_role NOT NULL,
  specialty        VARCHAR(255),
  display_name     VARCHAR(255) NOT NULL,
  description      TEXT,
  skills           TEXT[] NOT NULL DEFAULT '{}',
  provider         provider_type NOT NULL DEFAULT 'ollama',
  model_family     VARCHAR(100) NOT NULL DEFAULT 'prose',
  model            VARCHAR(255) NOT NULL,
  system_prompt_hash VARCHAR(64) REFERENCES content_blobs(content_hash),
  output_contract  JSONB NOT NULL DEFAULT '{}',
  policy_role      team_member_role REFERENCES role_github_policies(role),
  is_active        BOOLEAN NOT NULL DEFAULT TRUE,
  current_version  INTEGER NOT NULL DEFAULT 1,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE project_team_members (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id       UUID NOT NULL REFERENCES projects(id),
  team_member_id   UUID NOT NULL REFERENCES team_members(id),
  is_enabled       BOOLEAN NOT NULL DEFAULT TRUE,
  provider_override provider_type,
  model_override   VARCHAR(255),
  model_family_override VARCHAR(100),
  disabled_at      TIMESTAMPTZ,
  disable_reason   TEXT,
  current_version  INTEGER NOT NULL DEFAULT 1,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (project_id, team_member_id)
);

CREATE TABLE milestones (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id       UUID NOT NULL REFERENCES projects(id),
  title            VARCHAR(500) NOT NULL,
  description      TEXT,
  status           milestone_status NOT NULL DEFAULT 'planned',
  display_order    INTEGER NOT NULL DEFAULT 0,
  acceptance_criteria JSONB NOT NULL DEFAULT '[]',
  due_date         DATE,
  github_issue_id  VARCHAR(255),
  github_project_item VARCHAR(255),
  current_version  INTEGER NOT NULL DEFAULT 1,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE tasks (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id       UUID NOT NULL REFERENCES projects(id),
  milestone_id     UUID NOT NULL REFERENCES milestones(id),
  title            VARCHAR(500) NOT NULL,
  description      TEXT,
  status           task_status NOT NULL DEFAULT 'backlog',
  priority         task_priority NOT NULL DEFAULT 'medium',
  assigned_role    team_member_role,
  acceptance_criteria JSONB NOT NULL DEFAULT '[]',
  github_issue_number INTEGER,
  github_branch    VARCHAR(255),
  github_pr_number INTEGER,
  display_order    INTEGER NOT NULL DEFAULT 0,
  current_version  INTEGER NOT NULL DEFAULT 1,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- RUNS AND STEPS
-- ============================================================

CREATE TABLE runs (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id       UUID NOT NULL REFERENCES projects(id),
  milestone_id     UUID REFERENCES milestones(id),
  task_id          UUID REFERENCES tasks(id),
  status           run_status NOT NULL DEFAULT 'created',
  workflow_type    VARCHAR(100) NOT NULL DEFAULT 'sequential',
  trigger_actor    VARCHAR(255) NOT NULL,
  idempotency_key  VARCHAR(255) NOT NULL UNIQUE,
  attempt_number   INTEGER NOT NULL DEFAULT 1,
  parent_run_id    UUID REFERENCES runs(id),
  cancellation_policy VARCHAR(50) NOT NULL DEFAULT 'preserve_artifacts',
  started_at       TIMESTAMPTZ,
  paused_at        TIMESTAMPTZ,
  completed_at     TIMESTAMPTZ,
  error_message    TEXT,
  metadata         JSONB NOT NULL DEFAULT '{}',
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE run_steps (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  run_id           UUID NOT NULL REFERENCES runs(id),
  role             team_member_role NOT NULL,
  team_member_id   UUID REFERENCES team_members(id),
  model_used       VARCHAR(255),
  provider_used    provider_type,
  step_order       INTEGER NOT NULL,
  status           run_step_status NOT NULL DEFAULT 'pending',
  attempt_number   INTEGER NOT NULL DEFAULT 1,
  max_attempts     INTEGER NOT NULL DEFAULT 3,
  next_retry_at    TIMESTAMPTZ,
  input_artifact_id UUID,
  output_artifact_id UUID,
  started_at       TIMESTAMPTZ,
  completed_at     TIMESTAMPTZ,
  error_message    TEXT,
  token_count      INTEGER,
  latency_ms       INTEGER,
  metadata         JSONB NOT NULL DEFAULT '{}',
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (run_id, step_order)
);

-- ============================================================
-- ARTIFACTS, APPROVALS, COMMENTS
-- ============================================================

CREATE TABLE artifacts (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id       UUID NOT NULL REFERENCES projects(id),
  milestone_id     UUID REFERENCES milestones(id),
  task_id          UUID REFERENCES tasks(id),
  run_id           UUID REFERENCES runs(id),
  run_step_id      UUID REFERENCES run_steps(id),
  role             team_member_role,
  artifact_type    artifact_type NOT NULL,
  name             VARCHAR(255) NOT NULL,
  content_hash     VARCHAR(64) REFERENCES content_blobs(content_hash),
  storage_path     TEXT NOT NULL,
  version          INTEGER NOT NULL DEFAULT 1,
  is_current       BOOLEAN NOT NULL DEFAULT TRUE,
  superseded_by    UUID REFERENCES artifacts(id),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE approvals (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  entity_type      entity_type NOT NULL,
  entity_id        UUID NOT NULL,
  approved_revision_number INTEGER NOT NULL,
  status           approval_status NOT NULL DEFAULT 'pending',
  comment          TEXT NOT NULL,
  override_used    BOOLEAN NOT NULL DEFAULT FALSE,
  override_reason  TEXT,
  decided_by       VARCHAR(255) NOT NULL,
  is_stale         BOOLEAN NOT NULL DEFAULT FALSE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE approval_evidence (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  approval_id      UUID NOT NULL REFERENCES approvals(id) ON DELETE CASCADE,
  evidence_type    evidence_type NOT NULL,
  artifact_id      UUID REFERENCES artifacts(id),
  external_url     TEXT,
  description      TEXT NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE comments (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  entity_type      entity_type NOT NULL,
  entity_id        UUID NOT NULL,
  author           VARCHAR(255) NOT NULL,
  body             TEXT NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- REVISION AND AUDIT TABLES
-- ============================================================

CREATE TABLE revisions (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  entity_type      entity_type NOT NULL,
  entity_id        UUID NOT NULL,
  revision_number  INTEGER NOT NULL,
  actor            VARCHAR(255) NOT NULL,
  change_summary   TEXT NOT NULL,
  reason_category  reason_category NOT NULL,
  reason_detail    TEXT NOT NULL,
  reason_references JSONB NOT NULL DEFAULT '[]',
  before_snapshot  JSONB,
  after_snapshot   JSONB NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (entity_type, entity_id, revision_number)
);

CREATE TABLE decision_logs (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  run_id           UUID REFERENCES runs(id),
  run_step_id      UUID REFERENCES run_steps(id),
  decision_type    decision_type NOT NULL,
  input_summary    TEXT NOT NULL,
  output_summary   TEXT NOT NULL,
  rationale        TEXT NOT NULL,
  full_input       JSONB NOT NULL DEFAULT '{}',
  full_output      JSONB NOT NULL DEFAULT '{}',
  model_used       VARCHAR(255),
  latency_ms       INTEGER,
  token_count      INTEGER,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE prompt_eval_runs (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  team_member_id   UUID NOT NULL REFERENCES team_members(id),
  prompt_revision_number INTEGER NOT NULL,
  golden_task_key  VARCHAR(255) NOT NULL,
  model_used       VARCHAR(255),
  output_artifact_id UUID REFERENCES artifacts(id),
  human_score      NUMERIC(4,2),
  auto_score       NUMERIC(4,2),
  notes            TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- GITHUB AND SAFETY
-- ============================================================

CREATE TABLE github_sync (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  entity_type      entity_type NOT NULL,
  entity_id        UUID NOT NULL,
  github_object_type VARCHAR(50) NOT NULL,
  github_object_id VARCHAR(255) NOT NULL,
  github_url       TEXT,
  sync_status      VARCHAR(50) NOT NULL DEFAULT 'synced',
  metadata         JSONB NOT NULL DEFAULT '{}',
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE github_webhook_events (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  delivery_id      VARCHAR(255) NOT NULL UNIQUE,
  event_name       VARCHAR(100) NOT NULL,
  payload          JSONB NOT NULL,
  received_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE notifications (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  notification_type VARCHAR(100) NOT NULL,
  title            VARCHAR(255) NOT NULL,
  body             TEXT NOT NULL,
  is_read          BOOLEAN NOT NULL DEFAULT FALSE,
  metadata         JSONB NOT NULL DEFAULT '{}',
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE safety_violations (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  violation_type   violation_type NOT NULL,
  agent_role       team_member_role,
  run_id           UUID REFERENCES runs(id),
  run_step_id      UUID REFERENCES run_steps(id),
  attempted_action TEXT NOT NULL,
  context          JSONB NOT NULL DEFAULT '{}',
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX idx_projects_status ON projects(status);
CREATE INDEX idx_team_members_role ON team_members(role);
CREATE INDEX idx_team_members_model_family ON team_members(model_family);
CREATE INDEX idx_project_team_members_project ON project_team_members(project_id);
CREATE INDEX idx_milestones_project ON milestones(project_id);
CREATE INDEX idx_tasks_project ON tasks(project_id);
CREATE INDEX idx_tasks_milestone ON tasks(milestone_id);
CREATE INDEX idx_runs_project ON runs(project_id);
CREATE INDEX idx_runs_status ON runs(status);
CREATE INDEX idx_run_steps_run ON run_steps(run_id);
CREATE INDEX idx_run_steps_status ON run_steps(status);
CREATE INDEX idx_artifacts_run ON artifacts(run_id);
CREATE INDEX idx_revisions_lookup ON revisions(entity_type, entity_id, revision_number DESC);
CREATE INDEX idx_prompt_eval_team_member ON prompt_eval_runs(team_member_id, created_at DESC);
CREATE INDEX idx_github_sync_entity ON github_sync(entity_type, entity_id);
CREATE INDEX idx_notifications_read ON notifications(is_read, created_at DESC);
CREATE INDEX idx_safety_violations_role ON safety_violations(agent_role, created_at DESC);

-- ============================================================
-- TRIGGERS
-- ============================================================

CREATE OR REPLACE FUNCTION forbid_revision_mutation()
RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION 'revisions table is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_revisions_no_update
BEFORE UPDATE ON revisions
FOR EACH ROW EXECUTE FUNCTION forbid_revision_mutation();

CREATE TRIGGER trg_revisions_no_delete
BEFORE DELETE ON revisions
FOR EACH ROW EXECUTE FUNCTION forbid_revision_mutation();

CREATE OR REPLACE FUNCTION mark_approvals_stale()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE approvals
     SET is_stale = TRUE
   WHERE entity_type = NEW.entity_type
     AND entity_id = NEW.entity_id
     AND approved_revision_number < NEW.revision_number
     AND is_stale = FALSE;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_revisions_mark_stale_approvals
AFTER INSERT ON revisions
FOR EACH ROW EXECUTE FUNCTION mark_approvals_stale();
