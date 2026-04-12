-- Migration 007: add dev_output to artifact_type enum
-- Required for P5 dev agent output artifacts.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_enum
     WHERE enumtypid = 'artifact_type'::regtype
       AND enumlabel = 'dev_output'
  ) THEN
    ALTER TYPE artifact_type ADD VALUE 'dev_output';
  END IF;
END
$$;
