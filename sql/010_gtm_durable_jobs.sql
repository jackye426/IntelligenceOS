-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 010: Durable GTM pipeline jobs + match-review harden
-- Safe to re-run: IF NOT EXISTS / ADD COLUMN IF NOT EXISTS
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Durable jobs ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gtm_pipeline_jobs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kind            TEXT NOT NULL
                    CHECK (kind IN (
                      'doctify_extract_batch',
                      'doctify_discover',
                      'pipeline_scoped_run',
                      'cqc_rematch',
                      'other'
                    )),
  status          TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN (
                      'queued','running','completed','failed','cancelled'
                    )),
  params          JSONB NOT NULL DEFAULT '{}',
  meta            JSONB NOT NULL DEFAULT '{}',
  total_items     INTEGER NOT NULL DEFAULT 0,
  succeeded_items INTEGER NOT NULL DEFAULT 0,
  failed_items    INTEGER NOT NULL DEFAULT 0,
  error           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at      TIMESTAMPTZ,
  finished_at     TIMESTAMPTZ,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gtm_pipeline_jobs_status
  ON gtm_pipeline_jobs (status, created_at DESC);

CREATE TABLE IF NOT EXISTS gtm_pipeline_job_items (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id                  UUID NOT NULL REFERENCES gtm_pipeline_jobs (id) ON DELETE CASCADE,
  item_key                TEXT NOT NULL,
  payload                 JSONB NOT NULL DEFAULT '{}',
  status                  TEXT NOT NULL DEFAULT 'queued'
                            CHECK (status IN (
                              'queued','running','succeeded','failed','cancelled','skipped'
                            )),
  attempts                INTEGER NOT NULL DEFAULT 0,
  worker_id               TEXT,
  heartbeat_at            TIMESTAMPTZ,
  claimed_at              TIMESTAMPTZ,
  finished_at             TIMESTAMPTZ,
  error                   TEXT,
  result                  JSONB NOT NULL DEFAULT '{}',
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (job_id, item_key)
);

CREATE INDEX IF NOT EXISTS idx_gtm_pipeline_job_items_claim
  ON gtm_pipeline_job_items (job_id, status, created_at)
  WHERE status IN ('queued', 'running');

CREATE INDEX IF NOT EXISTS idx_gtm_pipeline_job_items_heartbeat
  ON gtm_pipeline_job_items (status, heartbeat_at)
  WHERE status = 'running';

-- Atomic claim helper (SKIP LOCKED)
CREATE OR REPLACE FUNCTION gtm_claim_job_items(
  p_job_id UUID,
  p_limit INTEGER,
  p_worker_id TEXT,
  p_stale_seconds INTEGER DEFAULT 600
)
RETURNS SETOF gtm_pipeline_job_items
LANGUAGE plpgsql
AS $$
BEGIN
  -- Reclaim stale running items for this job
  UPDATE gtm_pipeline_job_items
  SET status = 'queued',
      worker_id = NULL,
      claimed_at = NULL,
      heartbeat_at = NULL,
      updated_at = now()
  WHERE job_id = p_job_id
    AND status = 'running'
    AND (
      heartbeat_at IS NULL
      OR heartbeat_at < now() - make_interval(secs => p_stale_seconds)
    );

  RETURN QUERY
  WITH cte AS (
    SELECT id
    FROM gtm_pipeline_job_items
    WHERE job_id = p_job_id
      AND status = 'queued'
    ORDER BY created_at
    FOR UPDATE SKIP LOCKED
    LIMIT GREATEST(p_limit, 1)
  )
  UPDATE gtm_pipeline_job_items i
  SET status = 'running',
      worker_id = p_worker_id,
      claimed_at = now(),
      heartbeat_at = now(),
      attempts = i.attempts + 1,
      updated_at = now()
  FROM cte
  WHERE i.id = cte.id
  RETURNING i.*;
END;
$$;


-- ── Match reviews: linkable + dedupe ─────────────────────────────────────────

ALTER TABLE gtm_match_reviews
  ADD COLUMN IF NOT EXISTS clinic_intelligence_id UUID
    REFERENCES gtm_clinic_intelligence (id) ON DELETE SET NULL;

ALTER TABLE gtm_match_reviews
  ADD COLUMN IF NOT EXISTS clinic_account_id UUID
    REFERENCES clinic_accounts (id) ON DELETE SET NULL;

ALTER TABLE gtm_match_reviews
  ADD COLUMN IF NOT EXISTS dedupe_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_gtm_match_reviews_dedupe
  ON gtm_match_reviews (dedupe_key)
  WHERE dedupe_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_gtm_match_reviews_clinic_intel
  ON gtm_match_reviews (clinic_intelligence_id, status)
  WHERE clinic_intelligence_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_gtm_match_reviews_clinic_account
  ON gtm_match_reviews (clinic_account_id, status)
  WHERE clinic_account_id IS NOT NULL;


-- ── RLS ──────────────────────────────────────────────────────────────────────

ALTER TABLE gtm_pipeline_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE gtm_pipeline_job_items ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'gtm_pipeline_jobs' AND policyname = 'gtm_pipeline_jobs_select'
  ) THEN
    CREATE POLICY gtm_pipeline_jobs_select ON gtm_pipeline_jobs
      FOR SELECT TO authenticated USING (true);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'gtm_pipeline_jobs' AND policyname = 'gtm_pipeline_jobs_service_all'
  ) THEN
    CREATE POLICY gtm_pipeline_jobs_service_all ON gtm_pipeline_jobs
      FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'gtm_pipeline_job_items' AND policyname = 'gtm_pipeline_job_items_select'
  ) THEN
    CREATE POLICY gtm_pipeline_job_items_select ON gtm_pipeline_job_items
      FOR SELECT TO authenticated USING (true);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'gtm_pipeline_job_items' AND policyname = 'gtm_pipeline_job_items_service_all'
  ) THEN
    CREATE POLICY gtm_pipeline_job_items_service_all ON gtm_pipeline_job_items
      FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;
END $$;
