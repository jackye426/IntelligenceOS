-- ─────────────────────────────────────────────────────────────────────────────
-- DocMap Intelligence OS — Migration 003: Doctor Outreach Tables
--
-- Run AFTER 001_clinic_intelligence.sql and 002_embeddings.sql.
-- Safe to re-run: uses CREATE TABLE IF NOT EXISTS throughout.
--
-- Note: FK references integrated_practitioner_with_phin (the actual table name).
-- updated_at is managed by the application layer (no trigger — avoids $$ issues).
-- ─────────────────────────────────────────────────────────────────────────────


-- ── Doctor Outreach ───────────────────────────────────────────────────────────
-- One row per practitioner. Mirrors email_history.json intent.
-- Upserted by sync_whatsapp_and_history_to_supabase.py on each sync run.

CREATE TABLE IF NOT EXISTS public.doctor_outreach (
  practitioner_id              TEXT NOT NULL
    REFERENCES public.integrated_practitioner_with_phin (id)
    ON DELETE CASCADE,

  canonical_email              TEXT,
  normalized_name              TEXT,

  status                       TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'converted', 'dnc')),
  followup_stage               INTEGER NOT NULL DEFAULT 0
    CHECK (followup_stage BETWEEN 0 AND 3),

  last_sent_at                 TIMESTAMPTZ,
  replied_at                   TIMESTAMPTZ,
  last_subject                 TEXT,
  recommendation_count_at_send INTEGER,

  whatsapp_tally               INTEGER NOT NULL DEFAULT 0,
  last_recommended_at          TIMESTAMPTZ,
  last_rationale               TEXT,
  last_profile_url             TEXT,

  inserted_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT doctor_outreach_pkey PRIMARY KEY (practitioner_id)
);

CREATE INDEX IF NOT EXISTS doctor_outreach_status_idx
  ON public.doctor_outreach (status);
CREATE INDEX IF NOT EXISTS doctor_outreach_last_sent_at_idx
  ON public.doctor_outreach (last_sent_at);
CREATE INDEX IF NOT EXISTS doctor_outreach_last_recommended_at_idx
  ON public.doctor_outreach (last_recommended_at);
CREATE INDEX IF NOT EXISTS doctor_outreach_canonical_email_idx
  ON public.doctor_outreach (canonical_email);


-- ── Doctor Recommendation Events ──────────────────────────────────────────────
-- Append-only. One row per WhatsApp recommendation event.
-- Upserted by sync_whatsapp_and_history_to_supabase.py on each sync run.

CREATE TABLE IF NOT EXISTS public.doctor_recommendation_events (
  event_id         TEXT NOT NULL,
  practitioner_id  TEXT NOT NULL
    REFERENCES public.integrated_practitioner_with_phin (id)
    ON DELETE CASCADE,

  source           TEXT NOT NULL DEFAULT 'whatsapp',
  recommended_at   TIMESTAMPTZ,
  source_file      TEXT,
  source_timestamp TEXT,

  display_name     TEXT,
  title            TEXT,
  rationale        TEXT,
  profile_url      TEXT,
  urls             JSONB,
  raw_block        TEXT,

  inserted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT doctor_recommendation_events_pkey PRIMARY KEY (event_id)
);

CREATE INDEX IF NOT EXISTS doctor_reco_events_practitioner_id_idx
  ON public.doctor_recommendation_events (practitioner_id);
CREATE INDEX IF NOT EXISTS doctor_reco_events_recommended_at_idx
  ON public.doctor_recommendation_events (recommended_at);
CREATE INDEX IF NOT EXISTS doctor_reco_events_source_file_idx
  ON public.doctor_recommendation_events (source_file);
CREATE INDEX IF NOT EXISTS doctor_reco_events_urls_gin
  ON public.doctor_recommendation_events USING gin (urls);
