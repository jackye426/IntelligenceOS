-- DocMap Intelligence OS - Migration 005: TikTok metrics layers
--
-- Run AFTER: 004_mcp_sources.sql
--
-- Layers:
--   1. content_metric_snapshots  — Display API (and optional yt-dlp) time series
--   2. tiktok_studio_insights    — Studio /aweme/v2/data/insight/ quality metrics
--   3. tiktok_account_daily      — Business Center Overview.csv day rollups
--   4. tiktok_audience_snapshots — Business Center Followers_*.csv

CREATE TABLE IF NOT EXISTS content_metric_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  platform TEXT NOT NULL DEFAULT 'tiktok',
  platform_post_id TEXT NOT NULL,
  content_post_id UUID REFERENCES content_posts(id) ON DELETE SET NULL,
  source TEXT NOT NULL
    CHECK (source IN ('display_api', 'yt_dlp', 'studio_item_list', 'manual')),
  captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  raw JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_metric_snapshots_post_time
  ON content_metric_snapshots (platform, platform_post_id, captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_metric_snapshots_source_time
  ON content_metric_snapshots (source, captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_metric_snapshots_metrics
  ON content_metric_snapshots USING gin (metrics);


CREATE TABLE IF NOT EXISTS tiktok_studio_insights (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  platform_post_id TEXT NOT NULL,
  content_post_id UUID REFERENCES content_posts(id) ON DELETE SET NULL,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Normalized quality / distribution fields (see marketing_pipeline normalize)
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  -- Full insight payload (or subset) for debugging / re-derivation
  raw JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_studio_insights_post_time
  ON tiktok_studio_insights (platform_post_id, captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_studio_insights_metrics
  ON tiktok_studio_insights USING gin (metrics);


CREATE TABLE IF NOT EXISTS tiktok_account_daily (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_handle TEXT NOT NULL DEFAULT 'docmap',
  day DATE NOT NULL,
  source TEXT NOT NULL DEFAULT 'business_center_csv',
  video_views INTEGER,
  profile_views INTEGER,
  likes INTEGER,
  comments INTEGER,
  shares INTEGER,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_tiktok_account_daily UNIQUE (account_handle, day, source)
);

CREATE INDEX IF NOT EXISTS idx_tiktok_account_daily_day
  ON tiktok_account_daily (account_handle, day DESC);


CREATE TABLE IF NOT EXISTS tiktok_audience_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_handle TEXT NOT NULL DEFAULT 'docmap',
  captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  source TEXT NOT NULL DEFAULT 'business_center_csv',
  follower_count INTEGER,
  -- gender, territories, hourly activity, follower history excerpt
  demographics JSONB NOT NULL DEFAULT '{}'::jsonb,
  raw JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tiktok_audience_time
  ON tiktok_audience_snapshots (account_handle, captured_at DESC);
