-- Migration 006: add decision_log to artifact_type enum
-- Required for P4 PM agent decision log artifacts.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_enum
     WHERE enumtypid = 'artifact_type'::regtype
       AND enumlabel = 'decision_log'
  ) THEN
    ALTER TYPE artifact_type ADD VALUE 'decision_log';
  END IF;
END
$$;
