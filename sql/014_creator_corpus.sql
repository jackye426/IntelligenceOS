-- 014_creator_corpus.sql
-- Doctor-creator TikTok corpus (L1/L2 store + L3 job queue + stored guidelines).
-- Does NOT alter content_posts or document_embeddings.
-- Safe to re-run: IF NOT EXISTS / ADD COLUMN IF NOT EXISTS.

CREATE OR REPLACE FUNCTION creator_set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

-- ── Seeds ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS creator_seeds (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slice                TEXT NOT NULL
                         CHECK (slice IN ('global','uk','practitioner','graph','manual')),
  source_type          TEXT NOT NULL
                         CHECK (source_type IN (
                           'hashtag','keyword','user_search','graph_mention','manual'
                         )),
  value                TEXT NOT NULL,
  meta                 JSONB NOT NULL DEFAULT '{}',
  priority             INTEGER NOT NULL DEFAULT 50
                         CHECK (priority BETWEEN 0 AND 100),
  status               TEXT NOT NULL DEFAULT 'active'
                         CHECK (status IN ('active','exhausted','blocked','paused')),
  cursor               JSONB NOT NULL DEFAULT '{}',
  hits_total           INTEGER NOT NULL DEFAULT 0,
  unique_new_authors   INTEGER NOT NULL DEFAULT 0,
  doctor_yield         NUMERIC,
  customer_yield       NUMERIC,
  last_run_at          TIMESTAMPTZ,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_type, value)
);

CREATE INDEX IF NOT EXISTS idx_creator_seeds_slice_status
  ON creator_seeds (slice, status, priority DESC);

DROP TRIGGER IF EXISTS trg_creator_seeds_updated ON creator_seeds;
CREATE TRIGGER trg_creator_seeds_updated
  BEFORE UPDATE ON creator_seeds
  FOR EACH ROW EXECUTE FUNCTION creator_set_updated_at();

-- ── Discovery hits ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS creator_discovery_hits (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  seed_id                  UUID REFERENCES creator_seeds (id) ON DELETE SET NULL,
  run_id                   UUID,
  tiktok_user_id           TEXT NOT NULL,
  handle                   TEXT NOT NULL,
  video_id                 TEXT,
  author_nickname          TEXT,
  author_signature         TEXT,
  author_follower_count    INTEGER,
  seen_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (seed_id, tiktok_user_id)
);

CREATE INDEX IF NOT EXISTS idx_creator_discovery_hits_handle
  ON creator_discovery_hits (handle);

DROP TRIGGER IF EXISTS trg_creator_discovery_hits_updated ON creator_discovery_hits;
CREATE TRIGGER trg_creator_discovery_hits_updated
  BEFORE UPDATE ON creator_discovery_hits
  FOR EACH ROW EXECUTE FUNCTION creator_set_updated_at();

-- ── Profiles ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS creator_profiles (
  id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tiktok_user_id              TEXT NOT NULL UNIQUE,
  sec_uid                     TEXT,
  handle                      TEXT NOT NULL,
  handle_history              TEXT[] NOT NULL DEFAULT '{}',
  profile_url                 TEXT,
  nickname                    TEXT,
  bio                         TEXT,
  bio_link                    TEXT,
  follower_count              INTEGER,
  following_count             INTEGER,
  heart_count                 BIGINT,
  video_count                 INTEGER,
  verified                    BOOLEAN,
  is_organization             BOOLEAN,
  commerce_user               BOOLEAN,
  tt_seller                   BOOLEAN,
  language                    TEXT,
  private_account             BOOLEAN,
  account_created_at          TIMESTAMPTZ,
  profile_fetched_at          TIMESTAMPTZ,
  first_seen_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  seed_slices                 TEXT[] NOT NULL DEFAULT '{}',
  best_seed_priority          INTEGER,
  discovery_count             INTEGER NOT NULL DEFAULT 1,
  stage                       TEXT NOT NULL DEFAULT 'discovered'
                                CHECK (stage IN (
                                  'discovered','profiled','screened','hydrated',
                                  'classified','scored','excluded','unavailable'
                                )),
  work_status                 TEXT NOT NULL DEFAULT 'ready'
                                CHECK (work_status IN ('ready','leased','retry','blocked')),
  attempts                    INTEGER NOT NULL DEFAULT 0,
  next_attempt_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  lease_owner                 TEXT,
  lease_expires_at            TIMESTAMPTZ,
  last_error                  TEXT,
  excluded_reason             TEXT,
  screen_result               TEXT,
  screen_reasons              TEXT[] NOT NULL DEFAULT '{}',
  bio_emails                  TEXT[] NOT NULL DEFAULT '{}',
  bio_links                   JSONB NOT NULL DEFAULT '[]',
  bio_handles                 JSONB NOT NULL DEFAULT '{}',
  credential_signals          TEXT[] NOT NULL DEFAULT '{}',
  geo_signals                 JSONB NOT NULL DEFAULT '[]',
  gmc_number_in_bio           TEXT,
  recent_window_n             INTEGER,
  last_post_at                TIMESTAMPTZ,
  posts_30d                   INTEGER,
  posts_90d                   INTEGER,
  weeks_active_of_last_8      INTEGER,
  median_views                NUMERIC,
  median_engagement_rate      NUMERIC,
  median_saves_per_1k         NUMERIC,
  median_shares_per_1k        NUMERIC,
  median_duration_sec         NUMERIC,
  views_to_followers_median   NUMERIC,
  hydrate_status              TEXT
                                CHECK (hydrate_status IS NULL OR hydrate_status IN (
                                  'complete','partial'
                                )),
  hydrated_at                 TIMESTAMPTZ,
  insight_card_id             UUID,
  is_doctor                   BOOLEAN,
  doctor_confidence           NUMERIC,
  doctor_role                 TEXT,
  specialty_raw               TEXT,
  specialty_key               TEXT,
  geo_country                 TEXT,
  geo_confidence              NUMERIC,
  practice_setting            TEXT,
  growth_intent_level         INTEGER
                                CHECK (growth_intent_level IS NULL OR growth_intent_level BETWEEN 0 AND 3),
  positioning_line            TEXT,
  hook_jobs                   TEXT[] NOT NULL DEFAULT '{}',
  format_mix                  JSONB NOT NULL DEFAULT '{}',
  cta_mix                     JSONB NOT NULL DEFAULT '{}',
  lane                        TEXT
                                CHECK (lane IS NULL OR lane IN (
                                  'customer','research','both','discard','pending_review'
                                )),
  lane_reasons                TEXT[] NOT NULL DEFAULT '{}',
  customer_score              NUMERIC,
  research_score              NUMERIC,
  score_breakdown             JSONB NOT NULL DEFAULT '{}',
  score_coverage              NUMERIC,
  scoring_version             TEXT,
  scored_at                   TIMESTAMPTZ,
  review_status               TEXT
                                CHECK (review_status IS NULL OR review_status IN (
                                  'pending','confirmed','rejected'
                                )),
  review_lane_override        TEXT,
  reviewed_by                 TEXT,
  reviewed_at                 TIMESTAMPTZ,
  review_note                 TEXT,
  do_not_contact              BOOLEAN NOT NULL DEFAULT false,
  promoted_clinic_intelligence_id UUID,
  promoted_person_id          UUID,
  promoted_at                 TIMESTAMPTZ,
  peer_account_handle         TEXT,
  peer_promoted_at            TIMESTAMPTZ,
  deep_status                 TEXT NOT NULL DEFAULT 'none'
                                CHECK (deep_status IN (
                                  'none','queued','ingesting','ingested',
                                  'brief_draft','brief_failed','brief_confirmed'
                                )),
  deep_quality                TEXT
                                CHECK (deep_quality IS NULL OR deep_quality IN ('auto','on_demand')),
  deep_job_id                 UUID,
  good_fit                    BOOLEAN NOT NULL DEFAULT false,
  good_fit_version            TEXT,
  provenance                  JSONB NOT NULL DEFAULT '{}',
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_creator_profiles_handle
  ON creator_profiles (handle);

CREATE INDEX IF NOT EXISTS idx_creator_profiles_work
  ON creator_profiles (stage, work_status, next_attempt_at);

CREATE INDEX IF NOT EXISTS idx_creator_profiles_customer
  ON creator_profiles (lane, customer_score DESC);

CREATE INDEX IF NOT EXISTS idx_creator_profiles_research
  ON creator_profiles (lane, specialty_key, research_score DESC);

CREATE INDEX IF NOT EXISTS idx_creator_profiles_geo
  ON creator_profiles (geo_country);

CREATE INDEX IF NOT EXISTS idx_creator_profiles_review
  ON creator_profiles (review_status);

CREATE INDEX IF NOT EXISTS idx_creator_profiles_deep
  ON creator_profiles (deep_status);

CREATE INDEX IF NOT EXISTS idx_creator_profiles_good_fit
  ON creator_profiles (good_fit, research_score DESC);

DROP TRIGGER IF EXISTS trg_creator_profiles_updated ON creator_profiles;
CREATE TRIGGER trg_creator_profiles_updated
  BEFORE UPDATE ON creator_profiles
  FOR EACH ROW EXECUTE FUNCTION creator_set_updated_at();

-- ── Snapshots ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS creator_profile_snapshots (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  creator_profile_id   UUID NOT NULL REFERENCES creator_profiles (id) ON DELETE CASCADE,
  captured_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  follower_count       INTEGER,
  following_count      INTEGER,
  heart_count          BIGINT,
  video_count          INTEGER,
  source               TEXT,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_creator_profile_snapshots_profile
  ON creator_profile_snapshots (creator_profile_id, captured_at DESC);

DROP TRIGGER IF EXISTS trg_creator_profile_snapshots_updated ON creator_profile_snapshots;
CREATE TRIGGER trg_creator_profile_snapshots_updated
  BEFORE UPDATE ON creator_profile_snapshots
  FOR EACH ROW EXECUTE FUNCTION creator_set_updated_at();

-- ── Videos (L1/L2 captions only) ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS creator_videos (
  video_id             TEXT PRIMARY KEY,
  creator_profile_id   UUID NOT NULL REFERENCES creator_profiles (id) ON DELETE CASCADE,
  url                  TEXT,
  posted_at            TIMESTAMPTZ,
  duration_sec         NUMERIC,
  view_count           BIGINT,
  like_count           BIGINT,
  comment_count        BIGINT,
  share_count          BIGINT,
  save_count           BIGINT,
  caption              TEXT,
  caption_hook         TEXT,
  hashtags             TEXT[] NOT NULL DEFAULT '{}',
  mentions             TEXT[] NOT NULL DEFAULT '{}',
  stitch_or_duet_of    TEXT,
  first_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  metrics_updated_at   TIMESTAMPTZ,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_creator_videos_profile_posted
  ON creator_videos (creator_profile_id, posted_at DESC);

DROP TRIGGER IF EXISTS trg_creator_videos_updated ON creator_videos;
CREATE TRIGGER trg_creator_videos_updated
  BEFORE UPDATE ON creator_videos
  FOR EACH ROW EXECUTE FUNCTION creator_set_updated_at();

-- ── Insight cards ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS creator_insight_cards (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  creator_profile_id   UUID NOT NULL REFERENCES creator_profiles (id) ON DELETE CASCADE,
  classifier_version   TEXT NOT NULL,
  prompt_fingerprint   TEXT,
  model                TEXT,
  input_hash           TEXT NOT NULL,
  output               JSONB NOT NULL DEFAULT '{}',
  evidence             JSONB NOT NULL DEFAULT '[]',
  quote_validation     JSONB NOT NULL DEFAULT '{}',
  is_doctor            BOOLEAN,
  doctor_confidence    NUMERIC,
  doctor_role          TEXT,
  specialty_raw        TEXT,
  specialty_key        TEXT,
  geo_country          TEXT,
  geo_confidence       NUMERIC,
  practice_setting     TEXT,
  growth_intent_level  INTEGER,
  positioning_line     TEXT,
  named_promise        TEXT,
  who_it_is_for        TEXT,
  hook_jobs            TEXT[] NOT NULL DEFAULT '{}',
  content_formats      TEXT[] NOT NULL DEFAULT '{}',
  format_mix           JSONB NOT NULL DEFAULT '{}',
  cta_types            TEXT[] NOT NULL DEFAULT '{}',
  series_markers       TEXT[] NOT NULL DEFAULT '{}',
  caption_hooks        TEXT[] NOT NULL DEFAULT '{}',
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (creator_profile_id, classifier_version, input_hash)
);

CREATE INDEX IF NOT EXISTS idx_creator_insight_cards_profile
  ON creator_insight_cards (creator_profile_id, created_at DESC);

DROP TRIGGER IF EXISTS trg_creator_insight_cards_updated ON creator_insight_cards;
CREATE TRIGGER trg_creator_insight_cards_updated
  BEFORE UPDATE ON creator_insight_cards
  FOR EACH ROW EXECUTE FUNCTION creator_set_updated_at();

ALTER TABLE creator_profiles
  DROP CONSTRAINT IF EXISTS creator_profiles_insight_card_id_fkey;
ALTER TABLE creator_profiles
  ADD CONSTRAINT creator_profiles_insight_card_id_fkey
  FOREIGN KEY (insight_card_id) REFERENCES creator_insight_cards (id)
  ON DELETE SET NULL;

-- ── Specialty boards ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS creator_specialty_stats (
  specialty_key              TEXT PRIMARY KEY,
  n_doctors                  INTEGER NOT NULL DEFAULT 0,
  n_uk_private               INTEGER NOT NULL DEFAULT 0,
  n_deep_libraries           INTEGER NOT NULL DEFAULT 0,
  median_followers           NUMERIC,
  p25_followers              NUMERIC,
  p75_followers              NUMERIC,
  median_posts_30d           NUMERIC,
  median_saves_per_1k        NUMERIC,
  median_shares_per_1k       NUMERIC,
  median_views_to_followers  NUMERIC,
  format_histogram           JSONB NOT NULL DEFAULT '{}',
  cta_histogram              JSONB NOT NULL DEFAULT '{}',
  hook_job_histogram         JSONB NOT NULL DEFAULT '{}',
  median_duration_sec        NUMERIC,
  exemplar_handles           JSONB NOT NULL DEFAULT '{}',
  rebuilt_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_creator_specialty_stats_updated ON creator_specialty_stats;
CREATE TRIGGER trg_creator_specialty_stats_updated
  BEFORE UPDATE ON creator_specialty_stats
  FOR EACH ROW EXECUTE FUNCTION creator_set_updated_at();

-- ── L3 guidelines ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS creator_peer_briefs (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  creator_profile_id   UUID NOT NULL REFERENCES creator_profiles (id) ON DELETE CASCADE,
  account_handle       TEXT NOT NULL,
  status               TEXT NOT NULL DEFAULT 'draft'
                         CHECK (status IN ('draft','confirmed','rejected')),
  source               TEXT NOT NULL DEFAULT 'auto_job'
                         CHECK (source IN ('auto_job','mcp_session')),
  schema_version       TEXT NOT NULL DEFAULT 'content_guidelines_v1',
  artefact             JSONB NOT NULL DEFAULT '{}',
  evidence_video_ids   TEXT[] NOT NULL DEFAULT '{}',
  coverage             JSONB NOT NULL DEFAULT '{}',
  model                TEXT,
  confirmed_by         TEXT,
  confirmed_at         TIMESTAMPTZ,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_creator_peer_briefs_current
  ON creator_peer_briefs (account_handle)
  WHERE status IN ('draft','confirmed');

CREATE INDEX IF NOT EXISTS idx_creator_peer_briefs_profile
  ON creator_peer_briefs (creator_profile_id, created_at DESC);

DROP TRIGGER IF EXISTS trg_creator_peer_briefs_updated ON creator_peer_briefs;
CREATE TRIGGER trg_creator_peer_briefs_updated
  BEFORE UPDATE ON creator_peer_briefs
  FOR EACH ROW EXECUTE FUNCTION creator_set_updated_at();

-- ── Deep jobs (copy GTM durable jobs; 4h stale; do not reuse gtm_pipeline_jobs)

CREATE TABLE IF NOT EXISTS creator_deep_jobs (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kind             TEXT NOT NULL
                     CHECK (kind IN ('deep_ingest','write_brief')),
  status           TEXT NOT NULL DEFAULT 'queued'
                     CHECK (status IN (
                       'queued','running','completed','failed','cancelled'
                     )),
  params           JSONB NOT NULL DEFAULT '{}',
  meta             JSONB NOT NULL DEFAULT '{}',
  total_items      INTEGER NOT NULL DEFAULT 0,
  succeeded_items  INTEGER NOT NULL DEFAULT 0,
  failed_items     INTEGER NOT NULL DEFAULT 0,
  error            TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at       TIMESTAMPTZ,
  finished_at      TIMESTAMPTZ,
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_creator_deep_jobs_status
  ON creator_deep_jobs (kind, status, created_at DESC);

DROP TRIGGER IF EXISTS trg_creator_deep_jobs_updated ON creator_deep_jobs;
CREATE TRIGGER trg_creator_deep_jobs_updated
  BEFORE UPDATE ON creator_deep_jobs
  FOR EACH ROW EXECUTE FUNCTION creator_set_updated_at();

CREATE TABLE IF NOT EXISTS creator_deep_job_items (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id        UUID NOT NULL REFERENCES creator_deep_jobs (id) ON DELETE CASCADE,
  kind          TEXT NOT NULL
                  CHECK (kind IN ('deep_ingest','write_brief')),
  item_key      TEXT NOT NULL,
  priority      INTEGER NOT NULL DEFAULT 40,
  payload       JSONB NOT NULL DEFAULT '{}',
  status        TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN (
                    'queued','running','succeeded','failed','cancelled','skipped'
                  )),
  attempts      INTEGER NOT NULL DEFAULT 0,
  worker_id     TEXT,
  heartbeat_at  TIMESTAMPTZ,
  claimed_at    TIMESTAMPTZ,
  finished_at   TIMESTAMPTZ,
  error         TEXT,
  result        JSONB NOT NULL DEFAULT '{}',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (kind, item_key)
);

CREATE INDEX IF NOT EXISTS idx_creator_deep_job_items_claim
  ON creator_deep_job_items (kind, status, priority DESC, created_at)
  WHERE status IN ('queued','running');

DROP TRIGGER IF EXISTS trg_creator_deep_job_items_updated ON creator_deep_job_items;
CREATE TRIGGER trg_creator_deep_job_items_updated
  BEFORE UPDATE ON creator_deep_job_items
  FOR EACH ROW EXECUTE FUNCTION creator_set_updated_at();

-- ── Identity links ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS creator_links (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  creator_profile_id   UUID NOT NULL REFERENCES creator_profiles (id) ON DELETE CASCADE,
  target_table         TEXT NOT NULL
                         CHECK (target_table IN (
                           'integrated_practitioners','gtm_clinic_people',
                           'gtm_clinic_intelligence','doctor_outreach'
                         )),
  target_id            TEXT NOT NULL,
  method               TEXT NOT NULL
                         CHECK (method IN (
                           'gmc_in_bio','email_exact','bio_domain',
                           'name_specialty','name_only','manual'
                         )),
  confidence           NUMERIC,
  evidence             JSONB NOT NULL DEFAULT '{}',
  status               TEXT NOT NULL DEFAULT 'suggested'
                         CHECK (status IN ('suggested','confirmed','rejected')),
  reviewed_by          TEXT,
  reviewed_at          TIMESTAMPTZ,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (creator_profile_id, target_table, target_id)
);

CREATE INDEX IF NOT EXISTS idx_creator_links_status
  ON creator_links (status, method);

DROP TRIGGER IF EXISTS trg_creator_links_updated ON creator_links;
CREATE TRIGGER trg_creator_links_updated
  BEFORE UPDATE ON creator_links
  FOR EACH ROW EXECUTE FUNCTION creator_set_updated_at();

-- ── Crawl runs ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS creator_crawl_runs (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  command       TEXT NOT NULL,
  source        TEXT,
  params        JSONB NOT NULL DEFAULT '{}',
  status        TEXT NOT NULL DEFAULT 'running'
                  CHECK (status IN (
                    'running','completed','degraded','blocked','failed'
                  )),
  budget        JSONB NOT NULL DEFAULT '{}',
  counters      JSONB NOT NULL DEFAULT '{}',
  expectations  JSONB NOT NULL DEFAULT '{}',
  worker        TEXT,
  started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at   TIMESTAMPTZ,
  error         TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_creator_crawl_runs_started
  ON creator_crawl_runs (started_at DESC);

DROP TRIGGER IF EXISTS trg_creator_crawl_runs_updated ON creator_crawl_runs;
CREATE TRIGGER trg_creator_crawl_runs_updated
  BEFORE UPDATE ON creator_crawl_runs
  FOR EACH ROW EXECUTE FUNCTION creator_set_updated_at();

-- ── Profile claim RPC ────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION creator_claim(
  p_limit INTEGER,
  p_worker_id TEXT,
  p_stages TEXT[] DEFAULT ARRAY['discovered','profiled','screened','hydrated','classified'],
  p_stale_seconds INTEGER DEFAULT 900
)
RETURNS SETOF creator_profiles
LANGUAGE plpgsql
AS $$
BEGIN
  UPDATE creator_profiles
  SET work_status = 'ready',
      lease_owner = NULL,
      lease_expires_at = NULL,
      updated_at = now()
  WHERE work_status = 'leased'
    AND (
      lease_expires_at IS NULL
      OR lease_expires_at < now()
      OR (
        lease_expires_at IS NOT NULL
        AND lease_expires_at < now() - make_interval(secs => p_stale_seconds)
      )
    );

  RETURN QUERY
  WITH cte AS (
    SELECT id
    FROM creator_profiles
    WHERE work_status IN ('ready','retry')
      AND stage = ANY (p_stages)
      AND next_attempt_at <= now()
    ORDER BY best_seed_priority DESC NULLS LAST, first_seen_at
    FOR UPDATE SKIP LOCKED
    LIMIT GREATEST(p_limit, 1)
  )
  UPDATE creator_profiles p
  SET work_status = 'leased',
      lease_owner = p_worker_id,
      lease_expires_at = now() + make_interval(secs => p_stale_seconds),
      attempts = p.attempts + 1,
      updated_at = now()
  FROM cte
  WHERE p.id = cte.id
  RETURNING p.*;
END;
$$;

-- ── Deep-job claim RPC (priority desc; 4h stale default) ─────────────────────

CREATE OR REPLACE FUNCTION creator_claim_deep_job_items(
  p_limit INTEGER,
  p_worker_id TEXT,
  p_stale_seconds INTEGER DEFAULT 14400,
  p_kind TEXT DEFAULT NULL
)
RETURNS SETOF creator_deep_job_items
LANGUAGE plpgsql
AS $$
BEGIN
  UPDATE creator_deep_job_items
  SET status = 'queued',
      worker_id = NULL,
      claimed_at = NULL,
      heartbeat_at = NULL,
      updated_at = now()
  WHERE status = 'running'
    AND (p_kind IS NULL OR kind = p_kind)
    AND (
      heartbeat_at IS NULL
      OR heartbeat_at < now() - make_interval(secs => p_stale_seconds)
    );

  RETURN QUERY
  WITH cte AS (
    SELECT id
    FROM creator_deep_job_items
    WHERE status = 'queued'
      AND (p_kind IS NULL OR kind = p_kind)
    ORDER BY priority DESC, created_at
    FOR UPDATE SKIP LOCKED
    LIMIT GREATEST(p_limit, 1)
  )
  UPDATE creator_deep_job_items i
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

-- ── Views (security invoker so RLS applies) ──────────────────────────────────

CREATE OR REPLACE VIEW creator_corpus_current
WITH (security_invoker = true) AS
SELECT
  p.id,
  p.handle,
  p.profile_url,
  p.nickname,
  p.specialty_key,
  p.doctor_role,
  p.geo_country,
  p.follower_count,
  p.posts_30d,
  p.median_views,
  p.median_saves_per_1k,
  p.median_shares_per_1k,
  p.median_engagement_rate,
  (p.practice_setting IN ('private','mixed')) AS private_practice,
  p.growth_intent_level,
  p.positioning_line,
  p.lane,
  p.customer_score,
  p.research_score,
  p.score_coverage,
  p.review_status,
  (p.promoted_at IS NOT NULL) AS promoted,
  p.good_fit,
  p.deep_status,
  p.last_post_at,
  p.scored_at
FROM creator_profiles p
WHERE p.stage IN ('classified','scored');

CREATE OR REPLACE VIEW creator_customer_queue
WITH (security_invoker = true) AS
SELECT c.*, l.target_table AS best_link_table, l.method AS best_link_method, l.confidence AS best_link_confidence
FROM creator_corpus_current c
JOIN creator_profiles p ON p.id = c.id
LEFT JOIN LATERAL (
  SELECT *
  FROM creator_links
  WHERE creator_profile_id = p.id
    AND status IN ('suggested','confirmed')
  ORDER BY confidence DESC NULLS LAST
  LIMIT 1
) l ON true
WHERE c.lane IN ('customer','both')
  AND p.do_not_contact = false
  AND p.promoted_at IS NULL
ORDER BY c.customer_score DESC NULLS LAST;

CREATE OR REPLACE VIEW creator_research_board
WITH (security_invoker = true) AS
SELECT *
FROM creator_corpus_current
WHERE lane IN ('research','both')
ORDER BY specialty_key, research_score DESC NULLS LAST;

-- ── RLS ──────────────────────────────────────────────────────────────────────

DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'creator_seeds',
    'creator_discovery_hits',
    'creator_profiles',
    'creator_profile_snapshots',
    'creator_videos',
    'creator_insight_cards',
    'creator_specialty_stats',
    'creator_peer_briefs',
    'creator_deep_jobs',
    'creator_deep_job_items',
    'creator_links',
    'creator_crawl_runs'
  ]
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies WHERE tablename = t AND policyname = t || '_select'
    ) THEN
      EXECUTE format(
        'CREATE POLICY %I ON %I FOR SELECT TO authenticated USING (true)',
        t || '_select', t
      );
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies WHERE tablename = t AND policyname = t || '_service_all'
    ) THEN
      EXECUTE format(
        'CREATE POLICY %I ON %I FOR ALL TO service_role USING (true) WITH CHECK (true)',
        t || '_service_all', t
      );
    END IF;
  END LOOP;
END $$;
