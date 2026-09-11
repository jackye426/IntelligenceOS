-- 013a_match_documents.sql
--
-- Applied and verified against the live Supabase project on 2026-09-11.
-- Keep this standalone copy for repeatable recovery and new environments.
--
-- Context: sql/013_peer_libraries.sql was applied on 2026-09-10, but only the
-- content_posts half took effect. Verified live afterwards:
--   * content_posts.account_handle / owner_scope  -> present, 187/187 backfilled
--   * indexes + content_posts_handle_mismatch view -> present, 0 mismatches
--   * match_documents scoped rewrite               -> NOT applied
--
-- Before this was applied, two callers were broken because both already passed
-- filter_owner_scope to a function signature the database did not have:
--   * mcp-server/tools/search_knowledge.py   (MCP semantic search)
--   * app/api/chat/route.ts                  (chat retrieval route)
--
-- Safe to re-run. Re-running the whole of 013 is also safe (it is idempotent),
-- this file just avoids repeating the table DDL.
--
-- Verify afterwards with:  python scripts/verify-supabase-schema.py

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
