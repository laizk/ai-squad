-- Migration 008: add sandbox_result to artifact_type enum
-- Required for P5 dev agent sandbox execution artifacts.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_enum
     WHERE enumtypid = 'artifact_type'::regtype
       AND enumlabel = 'sandbox_result'
  ) THEN
    ALTER TYPE artifact_type ADD VALUE 'sandbox_result';
  END IF;
END
$$;
