-- 013_peer_libraries.sql
-- Peer content libraries: scope content_posts by account so a peer ingest cannot
-- be confused with, or destroy, the DocMap library.
--
-- Context: content_posts previously had NO account column. Every TikTok read
-- filtered on platform='tiktok' alone, and the sync's prune step deleted any
-- tiktok row outside the current run. Ingesting a second creator would both
-- displace DocMap rows from paginated reads and delete them on sync.
--
-- Safe to re-run.

-- ---------------------------------------------------------------------------
-- 1. Account scoping on content_posts
-- ---------------------------------------------------------------------------

ALTER TABLE content_posts
  ADD COLUMN IF NOT EXISTS account_handle TEXT NOT NULL DEFAULT 'docmap',
  ADD COLUMN IF NOT EXISTS owner_scope TEXT NOT NULL DEFAULT 'docmap';

-- Existing rows predate peer libraries and are all DocMap's.
UPDATE content_posts
   SET account_handle = 'docmap'
 WHERE account_handle IS NULL OR account_handle = '';

UPDATE content_posts
   SET owner_scope = 'docmap'
 WHERE owner_scope IS NULL OR owner_scope = '';

-- Primary read path: platform + account, newest first.
CREATE INDEX IF NOT EXISTS idx_content_posts_platform_account_posted
  ON content_posts (platform, account_handle, posted_at DESC);

-- Prune and upsert path.
CREATE INDEX IF NOT EXISTS idx_content_posts_account_post_id
  ON content_posts (account_handle, platform_post_id);

COMMENT ON COLUMN content_posts.account_handle IS
  'Creator handle this post belongs to (docmap | drleewarren | ...). Reads MUST filter on it.';
COMMENT ON COLUMN content_posts.owner_scope IS
  'Access scope: docmap for owned content, peer:<handle> for observed peer libraries.';

-- Semantic retrieval is DocMap-only unless a caller deliberately supplies a
-- different scope. Drop BOTH older overloads first, so no unscoped
-- implementation survives and PostgREST has exactly one candidate.
--
--   sql/002 created the 3-arg version. It predates owner_scope entirely and
--   filters nothing, so leaving it in place would keep a fully unscoped
--   retrieval path reachable by any 3-arg call — the peer isolation bypass this
--   migration exists to close.
--
--   sql/004 created the 4-arg version. It intended to replace the 3-arg one but
--   changed the signature, so it added an overload instead. That is why a call
--   omitting max_sensitivity currently fails with PGRST203 "could not choose the
--   best candidate function".
--
-- Verified 2026-09-10: no code calls the 3-arg or 4-arg form any more.
-- app/api/chat/route.ts and mcp-server/tools/search_knowledge.py both pass
-- filter_owner_scope; scripts/verify-supabase-schema.py was updated to match.
DROP FUNCTION IF EXISTS match_documents(vector, integer, text);
DROP FUNCTION IF EXISTS match_documents(vector, integer, text, text);

CREATE OR REPLACE FUNCTION match_documents(
  query_embedding vector(1536),
  match_count INT DEFAULT 8,
  filter_type TEXT DEFAULT NULL,
  max_sensitivity TEXT DEFAULT 'confidential',
  filter_owner_scope TEXT DEFAULT 'docmap'
)
RETURNS TABLE (
  id UUID,
  entity_type TEXT,
  entity_id UUID,
  source_table TEXT,
  source_title TEXT,
  source_url TEXT,
  chunk_index INTEGER,
  content TEXT,
  metadata JSONB,
  sensitivity TEXT,
  similarity FLOAT
)
LANGUAGE sql STABLE AS $$
  SELECT
    id,
    entity_type,
    entity_id,
    source_table,
    source_title,
    source_url,
    chunk_index,
    left(content, 1200) AS content,
    metadata,
    sensitivity,
    1 - (embedding <=> query_embedding) AS similarity
  FROM document_embeddings
  WHERE
    embedding IS NOT NULL
    AND owner_scope = filter_owner_scope
    AND (filter_type IS NULL OR entity_type = filter_type)
    AND (
      CASE max_sensitivity
        WHEN 'public' THEN sensitivity = 'public'
        WHEN 'internal' THEN sensitivity IN ('public','internal')
        WHEN 'confidential' THEN sensitivity IN ('public','internal','confidential')
        ELSE sensitivity IN ('public','internal','confidential','restricted')
      END
    )
  ORDER BY embedding <=> query_embedding
  LIMIT match_count;
$$;

-- ---------------------------------------------------------------------------
-- 2. Reference DDL for content_posts
-- ---------------------------------------------------------------------------
-- The table was created outside this repo, so the schema was not reviewable.
-- This is the shape the marketing pipeline and MCP tools rely on. It is a
-- no-op against the live table (IF NOT EXISTS) and exists for review.
--
-- Verified 2026-09-10 against the live table (project oewczjseteyvyvikxxaz) via
-- PostgREST: the column NAMES below match the live table exactly, in order.
-- Types and constraints are inferred from pipeline usage, not dumped from the
-- server, because no direct SQL connection was reachable at the time. Treat the
-- column list as authoritative and the type declarations as documentation.
-- Live state at that point: 187 rows, 185 of them platform='tiktok'.

CREATE TABLE IF NOT EXISTS content_posts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  platform TEXT NOT NULL,
  platform_post_id TEXT NOT NULL,
  account_handle TEXT NOT NULL DEFAULT 'docmap',
  owner_scope TEXT NOT NULL DEFAULT 'docmap',
  title TEXT,
  post_url TEXT,
  posted_at TIMESTAMPTZ,
  topic TEXT,
  format TEXT,
  hook TEXT,
  caption TEXT,
  transcript TEXT,
  metrics JSONB NOT NULL DEFAULT '{}',
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_content_posts_platform_post UNIQUE (platform, platform_post_id)
);

-- ---------------------------------------------------------------------------
-- 3. Guard view: any TikTok row whose URL handle disagrees with account_handle
-- ---------------------------------------------------------------------------
-- The catalog fetcher used to hardcode @docmap into every post_url. This view
-- surfaces rows where the stored URL and the account disagree, which means a
-- peer row is wearing a DocMap URL (or vice versa).

CREATE OR REPLACE VIEW content_posts_handle_mismatch AS
SELECT id,
       platform,
       platform_post_id,
       account_handle,
       post_url
  FROM content_posts
 WHERE platform = 'tiktok'
   AND post_url IS NOT NULL
   AND position('@' || account_handle || '/' in post_url) = 0;
