-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 011: Outreach cohorts + person LinkedIn contact fields
-- Safe to re-run: IF NOT EXISTS / ADD COLUMN IF NOT EXISTS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gtm_outreach_cohorts (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug          TEXT NOT NULL UNIQUE,
  name          TEXT NOT NULL,
  description   TEXT,
  rules         JSONB NOT NULL DEFAULT '{}',
  priority      INTEGER NOT NULL DEFAULT 50,
  active        BOOLEAN NOT NULL DEFAULT true,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gtm_outreach_cohort_members (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  cohort_id               UUID NOT NULL REFERENCES gtm_outreach_cohorts (id) ON DELETE CASCADE,
  clinic_intelligence_id  UUID NOT NULL REFERENCES gtm_clinic_intelligence (id) ON DELETE CASCADE,
  primary_specialty       TEXT,
  visible_clinic_size     TEXT,
  has_person_email        BOOLEAN NOT NULL DEFAULT false,
  best_person_id          UUID REFERENCES gtm_clinic_people (id) ON DELETE SET NULL,
  founder_score           INTEGER,
  status                  TEXT NOT NULL DEFAULT 'candidate'
                            CHECK (status IN (
                              'candidate','needs_contact','ready','found_linkedin','excluded'
                            )),
  reasons                 JSONB NOT NULL DEFAULT '[]',
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (cohort_id, clinic_intelligence_id)
);

CREATE INDEX IF NOT EXISTS idx_gtm_cohort_members_status
  ON gtm_outreach_cohort_members (cohort_id, status);

CREATE INDEX IF NOT EXISTS idx_gtm_cohort_members_clinic
  ON gtm_outreach_cohort_members (clinic_intelligence_id);

-- Person-level LinkedIn find (contact gaps only; does not overwrite clinic profile)
ALTER TABLE gtm_clinic_people
  ADD COLUMN IF NOT EXISTS linkedin_url TEXT;

ALTER TABLE gtm_clinic_people
  ADD COLUMN IF NOT EXISTS linkedin_status TEXT
    CHECK (
      linkedin_status IS NULL OR linkedin_status IN (
        'none','found','ambiguous','failed','skipped'
      )
    );

ALTER TABLE gtm_clinic_people
  ADD COLUMN IF NOT EXISTS linkedin_headline TEXT;

-- Seed cohorts (upsert by slug)
INSERT INTO gtm_outreach_cohorts (slug, name, description, rules, priority)
VALUES
  (
    'solo_og_fertility',
    'Solo/micro O&G fertility',
    'solo/micro clinics with O&G / fertility / menopause / endometriosis tags',
    '{
      "sizes": ["solo", "micro"],
      "specialty_keys": [
        "obstetrics_gynaecology", "fertility", "menopause", "endometriosis", "ivf"
      ],
      "require_people": true,
      "min_founder_score": null
    }'::jsonb,
    90
  ),
  (
    'small_derm',
    'Small+ dermatology',
    'small/mid/large dermatology clinics with people',
    '{
      "sizes": ["small", "mid", "large"],
      "specialty_keys": ["dermatology"],
      "require_people": true
    }'::jsonb,
    40
  ),
  (
    'needs_contact_priority',
    'Priority specialty needs contact',
    'Priority specialties, founder>=40, has people, no person email',
    '{
      "sizes": null,
      "specialty_keys": [
        "obstetrics_gynaecology", "fertility", "menopause", "endometriosis", "ivf"
      ],
      "require_people": true,
      "min_founder_score": 40,
      "require_no_person_email": true
    }'::jsonb,
    95
  )
ON CONFLICT (slug) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  rules = EXCLUDED.rules,
  priority = EXCLUDED.priority,
  updated_at = now();


ALTER TABLE gtm_outreach_cohorts ENABLE ROW LEVEL SECURITY;
ALTER TABLE gtm_outreach_cohort_members ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'gtm_outreach_cohorts' AND policyname = 'gtm_outreach_cohorts_select'
  ) THEN
    CREATE POLICY gtm_outreach_cohorts_select ON gtm_outreach_cohorts
      FOR SELECT TO authenticated USING (true);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'gtm_outreach_cohorts' AND policyname = 'gtm_outreach_cohorts_service_all'
  ) THEN
    CREATE POLICY gtm_outreach_cohorts_service_all ON gtm_outreach_cohorts
      FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'gtm_outreach_cohort_members' AND policyname = 'gtm_outreach_cohort_members_select'
  ) THEN
    CREATE POLICY gtm_outreach_cohort_members_select ON gtm_outreach_cohort_members
      FOR SELECT TO authenticated USING (true);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'gtm_outreach_cohort_members' AND policyname = 'gtm_outreach_cohort_members_service_all'
  ) THEN
    CREATE POLICY gtm_outreach_cohort_members_service_all ON gtm_outreach_cohort_members
      FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;
END $$;
