-- ─────────────────────────────────────────────────────────────────────────────
-- DocMap Intelligence OS — Migration 009: GTM Account Intelligence (P0)
--
-- Run after 008_relationship_context_memory.sql.
-- Safe to re-run: uses IF NOT EXISTS throughout.
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Clinic-level GTM intelligence ─────────────────────────────────────────────
-- One enrichment row per clinic_account (Doctify + CQC + scoring evidence).

CREATE TABLE IF NOT EXISTS gtm_clinic_intelligence (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_account_id         UUID REFERENCES clinic_accounts (id) ON DELETE SET NULL,
  doctify_url               TEXT,
  clinic_name               TEXT,
  website_url               TEXT,
  email                     TEXT,
  phone                     TEXT,
  address                   TEXT,
  postcode                  TEXT,
  bio                       TEXT,
  specialties               TEXT[] NOT NULL DEFAULT '{}',
  listed_specialist_count   INTEGER,
  visible_clinic_size       TEXT
                              CHECK (visible_clinic_size IS NULL OR visible_clinic_size IN (
                                'solo','micro','small','mid','large','unknown'
                              )),
  -- CQC
  cqc_location_id           TEXT,
  cqc_location_url          TEXT,
  cqc_registered_since      DATE,
  cqc_specialisms           TEXT[] NOT NULL DEFAULT '{}',
  cqc_registered_manager    TEXT,
  cqc_nominated_individual  TEXT,
  cqc_provider_name         TEXT,
  cqc_match_confidence      NUMERIC(4,3)
                              CHECK (cqc_match_confidence IS NULL OR cqc_match_confidence BETWEEN 0 AND 1),
  cqc_match_reasons         JSONB NOT NULL DEFAULT '[]',
  -- Scoring / structure
  founder_score             INTEGER CHECK (founder_score IS NULL OR founder_score BETWEEN 0 AND 100),
  structure                 TEXT,
  leadership_keywords       TEXT[] NOT NULL DEFAULT '{}',
  evidence                  JSONB NOT NULL DEFAULT '[]',
  provenance                JSONB NOT NULL DEFAULT '{}',
  scraped_at                TIMESTAMPTZ,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_gtm_clinic_intelligence_account
  ON gtm_clinic_intelligence (clinic_account_id)
  WHERE clinic_account_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_gtm_clinic_intelligence_doctify
  ON gtm_clinic_intelligence (doctify_url)
  WHERE doctify_url IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_gtm_clinic_intelligence_size
  ON gtm_clinic_intelligence (visible_clinic_size);

CREATE INDEX IF NOT EXISTS idx_gtm_clinic_intelligence_cqc
  ON gtm_clinic_intelligence (cqc_location_id);


-- ── People attached to a clinic ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gtm_clinic_people (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_intelligence_id    UUID REFERENCES gtm_clinic_intelligence (id) ON DELETE CASCADE,
  clinic_account_id         UUID REFERENCES clinic_accounts (id) ON DELETE SET NULL,
  full_name                 TEXT NOT NULL,
  role                      TEXT NOT NULL DEFAULT 'specialist',
  specialty                 TEXT,
  doctify_profile_url       TEXT,
  email                     TEXT,
  phone                     TEXT,
  priority                  INTEGER NOT NULL DEFAULT 50 CHECK (priority BETWEEN 0 AND 100),
  reasons                   JSONB NOT NULL DEFAULT '[]',
  evidence                  JSONB NOT NULL DEFAULT '[]',
  provenance                JSONB NOT NULL DEFAULT '{}',
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gtm_clinic_people_intel
  ON gtm_clinic_people (clinic_intelligence_id);

CREATE INDEX IF NOT EXISTS idx_gtm_clinic_people_account
  ON gtm_clinic_people (clinic_account_id);

CREATE INDEX IF NOT EXISTS idx_gtm_clinic_people_role
  ON gtm_clinic_people (role);

CREATE UNIQUE INDEX IF NOT EXISTS uq_gtm_clinic_people_doctify
  ON gtm_clinic_people (clinic_intelligence_id, doctify_profile_url)
  WHERE doctify_profile_url IS NOT NULL;


-- ── Ambiguous matches queued for human review (< 0.80) ───────────────────────

CREATE TABLE IF NOT EXISTS gtm_match_reviews (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type               TEXT NOT NULL
                              CHECK (entity_type IN (
                                'clinic_cqc','clinic_account','person_clinic','owner_clinic','other'
                              )),
  candidate                 JSONB NOT NULL DEFAULT '{}',
  target                    JSONB NOT NULL DEFAULT '{}',
  confidence                NUMERIC(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  reasons                   JSONB NOT NULL DEFAULT '[]',
  status                    TEXT NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending','approved','rejected','merged')),
  reviewed_by               TEXT,
  reviewed_at               TIMESTAMPTZ,
  notes                     TEXT,
  provenance                JSONB NOT NULL DEFAULT '{}',
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gtm_match_reviews_status
  ON gtm_match_reviews (status, confidence DESC);

CREATE INDEX IF NOT EXISTS idx_gtm_match_reviews_type
  ON gtm_match_reviews (entity_type);


-- ── Owner-first hits with no clinic link yet (never drop; keep email) ────────

CREATE TABLE IF NOT EXISTS gtm_unmatched_owners (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  practitioner_id           TEXT NOT NULL,
  full_name                 TEXT,
  email                     TEXT,
  about                     TEXT,
  leadership_role           TEXT,
  leadership_keywords       TEXT[] NOT NULL DEFAULT '{}',
  source_table              TEXT NOT NULL DEFAULT 'integrated_practitioners',
  evidence                  JSONB NOT NULL DEFAULT '[]',
  provenance                JSONB NOT NULL DEFAULT '{}',
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_gtm_unmatched_owners_practitioner
  ON gtm_unmatched_owners (practitioner_id);

CREATE INDEX IF NOT EXISTS uq_gtm_unmatched_owners_email
  ON gtm_unmatched_owners (lower(email))
  WHERE email IS NOT NULL;


-- ── RLS (service-role friendly; mirrors other internal clinic tables) ────────
-- App routes use the service role key. Authenticated users can read; only
-- service_role / postgres may write. Safe no-op if roles differ in local mocks.

ALTER TABLE gtm_clinic_intelligence ENABLE ROW LEVEL SECURITY;
ALTER TABLE gtm_clinic_people ENABLE ROW LEVEL SECURITY;
ALTER TABLE gtm_match_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE gtm_unmatched_owners ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'gtm_clinic_intelligence' AND policyname = 'gtm_clinic_intelligence_select'
  ) THEN
    CREATE POLICY gtm_clinic_intelligence_select ON gtm_clinic_intelligence
      FOR SELECT TO authenticated USING (true);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'gtm_clinic_people' AND policyname = 'gtm_clinic_people_select'
  ) THEN
    CREATE POLICY gtm_clinic_people_select ON gtm_clinic_people
      FOR SELECT TO authenticated USING (true);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'gtm_match_reviews' AND policyname = 'gtm_match_reviews_select'
  ) THEN
    CREATE POLICY gtm_match_reviews_select ON gtm_match_reviews
      FOR SELECT TO authenticated USING (true);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'gtm_unmatched_owners' AND policyname = 'gtm_unmatched_owners_select'
  ) THEN
    CREATE POLICY gtm_unmatched_owners_select ON gtm_unmatched_owners
      FOR SELECT TO authenticated USING (true);
  END IF;

  -- service_role bypasses RLS by default in Supabase; explicit write policies
  -- keep local/postgres setups consistent when JWT claims are present.
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'gtm_clinic_intelligence' AND policyname = 'gtm_clinic_intelligence_service_all'
  ) THEN
    CREATE POLICY gtm_clinic_intelligence_service_all ON gtm_clinic_intelligence
      FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'gtm_clinic_people' AND policyname = 'gtm_clinic_people_service_all'
  ) THEN
    CREATE POLICY gtm_clinic_people_service_all ON gtm_clinic_people
      FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'gtm_match_reviews' AND policyname = 'gtm_match_reviews_service_all'
  ) THEN
    CREATE POLICY gtm_match_reviews_service_all ON gtm_match_reviews
      FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'gtm_unmatched_owners' AND policyname = 'gtm_unmatched_owners_service_all'
  ) THEN
    CREATE POLICY gtm_unmatched_owners_service_all ON gtm_unmatched_owners
      FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;
END $$;
