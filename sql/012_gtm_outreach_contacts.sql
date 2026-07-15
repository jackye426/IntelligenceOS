-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 012: GTM outreach contacts (one PIC per clinic) + job kinds
-- Safe to re-run: IF NOT EXISTS / ADD COLUMN IF NOT EXISTS / constraint swap
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gtm_outreach_contacts (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_intelligence_id    UUID NOT NULL UNIQUE
                              REFERENCES gtm_clinic_intelligence (id) ON DELETE CASCADE,
  clinic_account_id         UUID REFERENCES clinic_accounts (id) ON DELETE SET NULL,
  person_id                 UUID REFERENCES gtm_clinic_people (id) ON DELETE SET NULL,
  full_name                 TEXT NOT NULL,
  role                      TEXT,
  email                     TEXT,
  email_source              TEXT
                              CHECK (
                                email_source IS NULL OR email_source IN (
                                  'practitioner','doctify','rocketreach','manual','none'
                                )
                              ),
  rocketreach_email         TEXT,
  rocketreach_status        TEXT
                              CHECK (
                                rocketreach_status IS NULL OR rocketreach_status IN (
                                  'none','found','ambiguous','failed','skipped','not_needed'
                                )
                              ),
  rocketreach_person_id     TEXT,
  linkedin_url              TEXT,
  linkedin_status           TEXT
                              CHECK (
                                linkedin_status IS NULL OR linkedin_status IN (
                                  'none','found','ambiguous','failed','skipped'
                                )
                              ),
  preferred_channel         TEXT NOT NULL DEFAULT 'none'
                              CHECK (preferred_channel IN ('email','linkedin','none')),
  priority                  INTEGER NOT NULL DEFAULT 50
                              CHECK (priority BETWEEN 0 AND 100),
  founder_score             INTEGER,
  status                    TEXT NOT NULL DEFAULT 'needs_enrichment'
                              CHECK (status IN (
                                'ready','needs_enrichment','needs_review','excluded'
                              )),
  evidence                  JSONB NOT NULL DEFAULT '[]',
  provenance                JSONB NOT NULL DEFAULT '{}',
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gtm_outreach_contacts_status
  ON gtm_outreach_contacts (status, preferred_channel);

CREATE INDEX IF NOT EXISTS idx_gtm_outreach_contacts_rr
  ON gtm_outreach_contacts (rocketreach_status)
  WHERE rocketreach_status IS NULL OR rocketreach_status IN ('none','failed');

CREATE INDEX IF NOT EXISTS idx_gtm_outreach_contacts_li
  ON gtm_outreach_contacts (linkedin_status)
  WHERE linkedin_url IS NULL;

ALTER TABLE gtm_outreach_contacts ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'gtm_outreach_contacts' AND policyname = 'gtm_outreach_contacts_select'
  ) THEN
    CREATE POLICY gtm_outreach_contacts_select ON gtm_outreach_contacts
      FOR SELECT TO authenticated USING (true);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'gtm_outreach_contacts' AND policyname = 'gtm_outreach_contacts_service_all'
  ) THEN
    CREATE POLICY gtm_outreach_contacts_service_all ON gtm_outreach_contacts
      FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;
END $$;

-- Expand durable job kinds (linkedin_find already used in code; add rocketreach)
DO $$
DECLARE
  conname text;
BEGIN
  SELECT c.conname INTO conname
  FROM pg_constraint c
  JOIN pg_class t ON c.conrelid = t.oid
  WHERE t.relname = 'gtm_pipeline_jobs'
    AND c.contype = 'c'
    AND pg_get_constraintdef(c.oid) ILIKE '%kind%';
  LIMIT 1;
  IF conname IS NOT NULL THEN
    EXECUTE format('ALTER TABLE gtm_pipeline_jobs DROP CONSTRAINT %I', conname);
  END IF;
  ALTER TABLE gtm_pipeline_jobs
    ADD CONSTRAINT gtm_pipeline_jobs_kind_check
    CHECK (kind IN (
      'doctify_extract_batch',
      'doctify_discover',
      'pipeline_scoped_run',
      'cqc_rematch',
      'linkedin_find',
      'rocketreach_enrich',
      'other'
    ));
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;
