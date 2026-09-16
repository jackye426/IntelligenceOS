-- 016_integrated_practitioners_rls.sql
-- Lock public.integrated_practitioners the same way as GTM clinic tables.
-- Authenticated may SELECT; service_role may do everything (and still bypasses RLS).
-- Safe to re-run.

ALTER TABLE integrated_practitioners ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'integrated_practitioners'
      AND policyname = 'integrated_practitioners_select'
  ) THEN
    CREATE POLICY integrated_practitioners_select ON integrated_practitioners
      FOR SELECT TO authenticated USING (true);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'integrated_practitioners'
      AND policyname = 'integrated_practitioners_service_all'
  ) THEN
    CREATE POLICY integrated_practitioners_service_all ON integrated_practitioners
      FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;
END $$;
