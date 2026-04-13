-- Safety violations table (P10 — Hardening)
-- Persists agent or infrastructure safety events for admin-web review.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'violation_severity') THEN
    CREATE TYPE violation_severity AS ENUM ('warning', 'critical');
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS safety_violations (
  id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  run_id        UUID REFERENCES runs(id) ON DELETE SET NULL,
  step_id       UUID REFERENCES run_steps(id) ON DELETE SET NULL,
  role          VARCHAR(50),
  violation_type VARCHAR(100) NOT NULL,
  severity      violation_severity NOT NULL DEFAULT 'warning',
  detail        TEXT NOT NULL,
  resolved      BOOLEAN NOT NULL DEFAULT FALSE,
  resolved_at   TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_safety_violations_run_id ON safety_violations(run_id);
CREATE INDEX IF NOT EXISTS idx_safety_violations_created_at ON safety_violations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_safety_violations_resolved ON safety_violations(resolved) WHERE resolved = FALSE;

GRANT SELECT, INSERT, UPDATE ON safety_violations TO squad_app;
