-- ─────────────────────────────────────────────────────────────────────────────
-- DocMap Intelligence OS — Migration 001: Core Schema
--
-- Run this in the Supabase SQL editor (supabase.com → SQL Editor).
-- Safe to re-run: uses CREATE TABLE IF NOT EXISTS throughout.
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Clinic Accounts ───────────────────────────────────────────────────────────
-- One row per clinic we are tracking as a sales target.

CREATE TABLE IF NOT EXISTS clinic_accounts (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name                TEXT NOT NULL,
  website_url         TEXT NOT NULL,
  owner_user          TEXT NOT NULL DEFAULT 'internal',
  pipeline_stage      TEXT NOT NULL DEFAULT 'Identified'
                        CHECK (pipeline_stage IN (
                          'Identified','Researching','Contact found',
                          'Outreach drafted','Contacted','Replied',
                          'Meeting booked','Demo completed','Proposal sent',
                          'Won','Lost','Paused'
                        )),
  fit_score           INTEGER NOT NULL DEFAULT 40 CHECK (fit_score BETWEEN 0 AND 100),
  sales_angle         TEXT,
  next_action         TEXT,
  next_action_due_at  DATE,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_clinic_accounts_stage      ON clinic_accounts (pipeline_stage);
CREATE INDEX IF NOT EXISTS idx_clinic_accounts_due        ON clinic_accounts (next_action_due_at);
CREATE INDEX IF NOT EXISTS idx_clinic_accounts_website    ON clinic_accounts (website_url);
CREATE INDEX IF NOT EXISTS idx_clinic_accounts_deleted    ON clinic_accounts (deleted_at);

-- Note: updated_at is managed by the application layer (PATCH routes set it explicitly).


-- ── Clinic Sources ────────────────────────────────────────────────────────────
-- Raw captured material: website pages, manual notes, email threads, meeting notes.
-- Every observation must trace back to a source row.

CREATE TABLE IF NOT EXISTS clinic_sources (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_account_id UUID NOT NULL REFERENCES clinic_accounts (id) ON DELETE CASCADE,
  type              TEXT NOT NULL
                      CHECK (type IN ('website_page','manual_note','email_thread','meeting_note')),
  url               TEXT,
  title             TEXT NOT NULL,
  captured_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  raw_text          TEXT NOT NULL DEFAULT '',
  content_hash      TEXT NOT NULL DEFAULT '',
  approved_for_use  BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_clinic_sources_account ON clinic_sources (clinic_account_id);
CREATE INDEX IF NOT EXISTS idx_clinic_sources_hash    ON clinic_sources (content_hash);


-- ── Clinic Research Runs ──────────────────────────────────────────────────────
-- Tracks each ingestion attempt: queued → fetching → extracting → needs_review → approved | failed.

CREATE TABLE IF NOT EXISTS clinic_research_runs (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_account_id UUID NOT NULL REFERENCES clinic_accounts (id) ON DELETE CASCADE,
  status            TEXT NOT NULL DEFAULT 'queued'
                      CHECK (status IN ('queued','fetching','extracting','needs_review','approved','failed')),
  submitted_url     TEXT NOT NULL,
  allowed_domain    TEXT NOT NULL,
  started_at        TIMESTAMPTZ,
  finished_at       TIMESTAMPTZ,
  error             TEXT,
  created_by_user   TEXT NOT NULL DEFAULT 'internal',
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_research_runs_account ON clinic_research_runs (clinic_account_id);
CREATE INDEX IF NOT EXISTS idx_research_runs_status  ON clinic_research_runs (status);


-- ── Clinic Observations ───────────────────────────────────────────────────────
-- Evidence-backed observations about patient journey, pricing, services, etc.

CREATE TABLE IF NOT EXISTS clinic_observations (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_account_id UUID NOT NULL REFERENCES clinic_accounts (id) ON DELETE CASCADE,
  source_id         UUID REFERENCES clinic_sources (id) ON DELETE SET NULL,
  category          TEXT NOT NULL
                      CHECK (category IN ('patient_journey','pricing','service','contact_route','positioning')),
  text              TEXT NOT NULL,
  confidence        NUMERIC(3,2) NOT NULL DEFAULT 0.5 CHECK (confidence BETWEEN 0 AND 1),
  review_status     TEXT NOT NULL DEFAULT 'draft'
                      CHECK (review_status IN ('draft','approved','rejected'))
);

CREATE INDEX IF NOT EXISTS idx_observations_account ON clinic_observations (clinic_account_id);
CREATE INDEX IF NOT EXISTS idx_observations_status  ON clinic_observations (review_status);


-- ── Clinic Contacts ───────────────────────────────────────────────────────────
-- People associated with the clinic: decision-makers, champions, gatekeepers.

CREATE TABLE IF NOT EXISTS clinic_contacts (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_account_id UUID NOT NULL REFERENCES clinic_accounts (id) ON DELETE CASCADE,
  name              TEXT NOT NULL,
  role              TEXT NOT NULL,
  email             TEXT,
  phone             TEXT,
  source_id         UUID REFERENCES clinic_sources (id) ON DELETE SET NULL,
  confidence        NUMERIC(3,2) NOT NULL DEFAULT 0.5,
  review_status     TEXT NOT NULL DEFAULT 'draft'
                      CHECK (review_status IN ('draft','approved','rejected'))
);

CREATE INDEX IF NOT EXISTS idx_contacts_account ON clinic_contacts (clinic_account_id);


-- ── Clinic Interactions ───────────────────────────────────────────────────────
-- Immutable log of all touchpoints: emails, calls, notes, system events.

CREATE TABLE IF NOT EXISTS clinic_interactions (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_account_id UUID NOT NULL REFERENCES clinic_accounts (id) ON DELETE CASCADE,
  type              TEXT NOT NULL
                      CHECK (type IN ('manual_note','email_thread','meeting_note','call','system_event')),
  body              TEXT NOT NULL,
  occurred_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by_user   TEXT NOT NULL DEFAULT 'internal',
  source_id         UUID REFERENCES clinic_sources (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_interactions_account     ON clinic_interactions (clinic_account_id);
CREATE INDEX IF NOT EXISTS idx_interactions_occurred_at ON clinic_interactions (occurred_at DESC);


-- ── Outreach Drafts ───────────────────────────────────────────────────────────
-- Human-reviewed outreach copy. Never sent automatically.

CREATE TABLE IF NOT EXISTS outreach_drafts (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_account_id     UUID NOT NULL REFERENCES clinic_accounts (id) ON DELETE CASCADE,
  subject               TEXT NOT NULL,
  body                  TEXT NOT NULL,
  tone                  TEXT NOT NULL DEFAULT 'direct',
  status                TEXT NOT NULL DEFAULT 'draft'
                          CHECK (status IN ('draft','approved','sent_elsewhere','archived')),
  generated_from_run_id UUID REFERENCES clinic_research_runs (id) ON DELETE SET NULL,
  approved_by_user      TEXT,
  approved_at           TIMESTAMPTZ,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_drafts_account ON outreach_drafts (clinic_account_id);
CREATE INDEX IF NOT EXISTS idx_drafts_status  ON outreach_drafts (status);


-- ── Pipeline Stage History ────────────────────────────────────────────────────
-- Immutable event log. Append-only; rows are never updated or deleted.

CREATE TABLE IF NOT EXISTS pipeline_stage_history (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_account_id UUID NOT NULL REFERENCES clinic_accounts (id) ON DELETE CASCADE,
  from_stage        TEXT,
  to_stage          TEXT NOT NULL,
  changed_by_user   TEXT NOT NULL DEFAULT 'internal',
  changed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  reason            TEXT
);

CREATE INDEX IF NOT EXISTS idx_stage_history_account ON pipeline_stage_history (clinic_account_id);
CREATE INDEX IF NOT EXISTS idx_stage_history_at      ON pipeline_stage_history (changed_at DESC);


-- ── Account Tasks ─────────────────────────────────────────────────────────────
-- Next actions and follow-up tasks tied to an account.

CREATE TABLE IF NOT EXISTS account_tasks (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_account_id UUID NOT NULL REFERENCES clinic_accounts (id) ON DELETE CASCADE,
  owner_user        TEXT NOT NULL DEFAULT 'internal',
  title             TEXT NOT NULL,
  status            TEXT NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open','done','cancelled')),
  due_at            DATE,
  completed_at      TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tasks_account ON account_tasks (clinic_account_id);
CREATE INDEX IF NOT EXISTS idx_tasks_owner   ON account_tasks (owner_user);
CREATE INDEX IF NOT EXISTS idx_tasks_status  ON account_tasks (status);
CREATE INDEX IF NOT EXISTS idx_tasks_due     ON account_tasks (due_at);


-- ── Doctify Profiles ──────────────────────────────────────────────────────────
-- Raw scraped Doctify clinic cards. Linked to a clinic_account once a research
-- run is created from them.

CREATE TABLE IF NOT EXISTS doctify_profiles (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_name       TEXT NOT NULL,
  doctify_url       TEXT NOT NULL UNIQUE,
  website_url       TEXT,
  location          TEXT,
  specialty_tags    TEXT[] NOT NULL DEFAULT '{}',
  specialist_count  INTEGER,
  review_count      INTEGER,
  raw_json          JSONB NOT NULL DEFAULT '{}',
  scraped_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  clinic_account_id UUID REFERENCES clinic_accounts (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_doctify_account   ON doctify_profiles (clinic_account_id);
CREATE INDEX IF NOT EXISTS idx_doctify_scraped   ON doctify_profiles (scraped_at DESC);
