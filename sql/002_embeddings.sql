-- ─────────────────────────────────────────────────────────────────────────────
-- DocMap Intelligence OS — Migration 002: pgvector Embeddings
--
-- Run AFTER 001_clinic_intelligence.sql.
-- Requires the pgvector extension to be enabled in your Supabase project:
--   Database → Extensions → vector → Enable
-- ─────────────────────────────────────────────────────────────────────────────

-- Enable pgvector (idempotent).
CREATE EXTENSION IF NOT EXISTS vector;

-- ── Document Embeddings ───────────────────────────────────────────────────────
-- Stores vector embeddings for any entity so Ask DocMap can do semantic search.
-- The vector dimension (1536) matches OpenAI/OpenRouter text-embedding-3-small.

CREATE TABLE IF NOT EXISTS document_embeddings (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type  TEXT NOT NULL,   -- 'clinic_account' | 'observation' | 'outreach_draft' | ...
  entity_id    UUID NOT NULL,
  content      TEXT NOT NULL,   -- the text that was embedded (for display in citations)
  embedding    vector(1536),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_embeddings_entity
  ON document_embeddings (entity_type, entity_id);

-- IVFFlat index for fast approximate nearest-neighbour search.
-- Rebuild with more lists as the row count grows beyond ~100k.
CREATE INDEX IF NOT EXISTS idx_embeddings_vector
  ON document_embeddings USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);


-- ── Similarity search function ────────────────────────────────────────────────
-- Called from the /api/chat route to retrieve top-k relevant chunks.

CREATE OR REPLACE FUNCTION match_documents(
  query_embedding vector(1536),
  match_count     INT DEFAULT 8,
  filter_type     TEXT DEFAULT NULL  -- optionally restrict to one entity_type
)
RETURNS TABLE (
  id          UUID,
  entity_type TEXT,
  entity_id   UUID,
  content     TEXT,
  similarity  FLOAT
)
LANGUAGE sql STABLE AS $$
  SELECT
    id,
    entity_type,
    entity_id,
    content,
    1 - (embedding <=> query_embedding) AS similarity
  FROM document_embeddings
  WHERE
    embedding IS NOT NULL
    AND (filter_type IS NULL OR entity_type = filter_type)
  ORDER BY embedding <=> query_embedding
  LIMIT match_count;
$$;
