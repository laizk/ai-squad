DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'approval_status') THEN
    CREATE TYPE approval_status AS ENUM ('pending', 'approved', 'rejected', 'changes_requested');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'evidence_type') THEN
    CREATE TYPE evidence_type AS ENUM ('artifact', 'test_result', 'screenshot', 'log', 'github_link', 'other');
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS approvals (
  id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  entity_type              entity_type NOT NULL,
  entity_id                UUID NOT NULL,
  approved_revision_number INTEGER NOT NULL CHECK (approved_revision_number >= 1),
  status                   approval_status NOT NULL DEFAULT 'pending',
  comment                  TEXT NOT NULL,
  override_used            BOOLEAN NOT NULL DEFAULT FALSE,
  override_reason          TEXT,
  is_stale                 BOOLEAN NOT NULL DEFAULT FALSE,
  stale_at                 TIMESTAMPTZ,
  decided_by               VARCHAR(255) NOT NULL DEFAULT 'human:local',
  decided_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS approval_evidence (
  id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  approval_id   UUID NOT NULL REFERENCES approvals(id) ON DELETE CASCADE,
  evidence_type evidence_type NOT NULL,
  artifact_id   UUID,
  external_url  TEXT,
  description   TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_approvals_entity ON approvals(entity_type, entity_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_approvals_stale ON approvals(entity_type, entity_id, is_stale);
CREATE INDEX IF NOT EXISTS idx_approval_evidence_lookup ON approval_evidence(approval_id, created_at ASC);

GRANT SELECT, INSERT, UPDATE ON approvals TO squad_app;
GRANT SELECT, INSERT ON approval_evidence TO squad_app;
