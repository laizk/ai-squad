DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
      FROM pg_constraint
     WHERE conname = 'approval_evidence_artifact_id_fkey'
  ) THEN
    ALTER TABLE approval_evidence
      ADD CONSTRAINT approval_evidence_artifact_id_fkey
      FOREIGN KEY (artifact_id) REFERENCES artifacts(id);
  END IF;
END
$$;
