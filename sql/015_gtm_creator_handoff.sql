-- 015_gtm_creator_handoff.sql
-- Plug creator-corpus customers into existing GTM tables.
-- Run after 014_creator_corpus.sql.
-- Safe to re-run.

ALTER TABLE gtm_clinic_intelligence
  ADD COLUMN IF NOT EXISTS source_creator_profile_id UUID
    REFERENCES creator_profiles (id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_gtm_clinic_intelligence_source_creator
  ON gtm_clinic_intelligence (source_creator_profile_id)
  WHERE source_creator_profile_id IS NOT NULL;

ALTER TABLE gtm_clinic_people
  ADD COLUMN IF NOT EXISTS creator_profile_id UUID
    REFERENCES creator_profiles (id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_gtm_clinic_people_creator_profile
  ON gtm_clinic_people (creator_profile_id)
  WHERE creator_profile_id IS NOT NULL;

ALTER TABLE gtm_clinic_people
  ADD COLUMN IF NOT EXISTS social_profiles JSONB NOT NULL DEFAULT '{}';

-- Allow tiktok_bio as an outreach email source (constraint swap, same as 012).
DO $$
DECLARE
  conname text;
BEGIN
  SELECT c.conname INTO conname
  FROM pg_constraint c
  JOIN pg_class t ON c.conrelid = t.oid
  WHERE t.relname = 'gtm_outreach_contacts'
    AND c.contype = 'c'
    AND pg_get_constraintdef(c.oid) ILIKE '%email_source%'
  LIMIT 1;
  IF conname IS NOT NULL THEN
    EXECUTE format('ALTER TABLE gtm_outreach_contacts DROP CONSTRAINT %I', conname);
  END IF;
  ALTER TABLE gtm_outreach_contacts
    ADD CONSTRAINT gtm_outreach_contacts_email_source_check
    CHECK (
      email_source IS NULL OR email_source IN (
        'practitioner','doctify','rocketreach','manual','none','tiktok_bio'
      )
    );
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

INSERT INTO gtm_outreach_cohorts (slug, name, description, rules, priority)
VALUES (
  'tiktok_doctor_creators',
  'TikTok doctor creators',
  'UK private-practice doctors sourced from the creator corpus (not Doctify size/specialty scan)',
  '{"source":"creator_corpus","require_people":true}'::jsonb,
  85
)
ON CONFLICT (slug) DO UPDATE
SET description = EXCLUDED.description,
    rules = EXCLUDED.rules,
    priority = EXCLUDED.priority,
    updated_at = now();
