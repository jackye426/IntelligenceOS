-- DocMap Intelligence OS - Migration 004: MCP source metadata and safer RAG
--
-- Run AFTER:
--   001_clinic_intelligence.sql
--   002_embeddings.sql
--   003_doctor_outreach.sql
--
-- Purpose:
--   1. Add metadata tables for non-clinic sources used by the MCP server.
--   2. Add citation, chunking, and sensitivity fields to document_embeddings.
--   3. Replace match_documents with a version that returns cited chunks only.

CREATE EXTENSION IF NOT EXISTS vector;

-- Extend document_embeddings for MCP-grade citations and privacy filtering.
ALTER TABLE document_embeddings
  ADD COLUMN IF NOT EXISTS source_table TEXT,
  ADD COLUMN IF NOT EXISTS source_title TEXT,
  ADD COLUMN IF NOT EXISTS source_url TEXT,
  ADD COLUMN IF NOT EXISTS chunk_index INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS content_hash TEXT,
  ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS sensitivity TEXT NOT NULL DEFAULT 'internal'
    CHECK (sensitivity IN ('public','internal','confidential','restricted')),
  ADD COLUMN IF NOT EXISTS owner_scope TEXT NOT NULL DEFAULT 'docmap';

CREATE INDEX IF NOT EXISTS idx_embeddings_type_sensitivity
  ON document_embeddings (entity_type, sensitivity);

CREATE INDEX IF NOT EXISTS idx_embeddings_hash
  ON document_embeddings (content_hash);

CREATE INDEX IF NOT EXISTS idx_embeddings_metadata
  ON document_embeddings USING gin (metadata);

CREATE UNIQUE INDEX IF NOT EXISTS uq_embeddings_entity_chunk
  ON document_embeddings (entity_type, entity_id, chunk_index);


CREATE TABLE IF NOT EXISTS email_threads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  gmail_thread_id TEXT NOT NULL UNIQUE,
  account_email TEXT NOT NULL,
  subject TEXT,
  participants JSONB NOT NULL DEFAULT '[]',
  message_count INTEGER NOT NULL DEFAULT 0,
  first_message_at TIMESTAMPTZ,
  last_message_at TIMESTAMPTZ,
  labels TEXT[] NOT NULL DEFAULT '{}',
  source_hash TEXT,
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_email_threads_account
  ON email_threads (account_email);

CREATE INDEX IF NOT EXISTS idx_email_threads_last_message
  ON email_threads (last_message_at DESC);


CREATE TABLE IF NOT EXISTS patient_conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_system TEXT NOT NULL DEFAULT 'whatsapp',
  source_id TEXT NOT NULL,
  conversation_date DATE,
  condition_tags TEXT[] NOT NULL DEFAULT '{}',
  need_tags TEXT[] NOT NULL DEFAULT '{}',
  message_count INTEGER NOT NULL DEFAULT 0,
  contains_pii BOOLEAN NOT NULL DEFAULT TRUE,
  source_hash TEXT,
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_patient_conversation_source UNIQUE (source_system, source_id)
);

CREATE INDEX IF NOT EXISTS idx_patient_conversations_tags
  ON patient_conversations USING gin (condition_tags);


CREATE TABLE IF NOT EXISTS call_transcripts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_system TEXT NOT NULL DEFAULT 'google_drive',
  source_id TEXT NOT NULL,
  title TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'internal'
    CHECK (category IN ('internal','clinic','patient','content','unknown')),
  occurred_at TIMESTAMPTZ,
  participants JSONB NOT NULL DEFAULT '[]',
  source_url TEXT,
  source_hash TEXT,
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_call_transcript_source UNIQUE (source_system, source_id)
);

CREATE INDEX IF NOT EXISTS idx_call_transcripts_category
  ON call_transcripts (category);

CREATE INDEX IF NOT EXISTS idx_call_transcripts_occurred
  ON call_transcripts (occurred_at DESC);


CREATE TABLE IF NOT EXISTS content_posts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  platform TEXT NOT NULL,
  platform_post_id TEXT,
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
  CONSTRAINT uq_content_posts_platform_id UNIQUE (platform, platform_post_id)
);

CREATE INDEX IF NOT EXISTS idx_content_posts_platform
  ON content_posts (platform);

CREATE INDEX IF NOT EXISTS idx_content_posts_posted
  ON content_posts (posted_at DESC);

CREATE INDEX IF NOT EXISTS idx_content_posts_metrics
  ON content_posts USING gin (metrics);


CREATE TABLE IF NOT EXISTS appointment_slots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_system TEXT NOT NULL DEFAULT 'hca_monitor',
  source_slot_id TEXT,
  practitioner_name TEXT NOT NULL,
  practitioner_id TEXT,
  location TEXT,
  specialty TEXT,
  starts_at TIMESTAMPTZ NOT NULL,
  ends_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'visible'
    CHECK (status IN ('visible','booked','expired','disappeared','unknown')),
  booking_url TEXT,
  metadata JSONB NOT NULL DEFAULT '{}',
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_appointment_slots_source
  ON appointment_slots (source_system, source_slot_id)
  WHERE source_slot_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_appointment_slots_practitioner
  ON appointment_slots (practitioner_name);

CREATE INDEX IF NOT EXISTS idx_appointment_slots_starts
  ON appointment_slots (starts_at);

CREATE INDEX IF NOT EXISTS idx_appointment_slots_status
  ON appointment_slots (status);


CREATE TABLE IF NOT EXISTS booking_guids (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_system TEXT NOT NULL DEFAULT 'hca_monitor',
  practitioner_name TEXT,
  booking_guid TEXT NOT NULL,
  booking_url TEXT,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  metadata JSONB NOT NULL DEFAULT '{}',
  CONSTRAINT uq_booking_guid UNIQUE (source_system, booking_guid)
);


CREATE TABLE IF NOT EXISTS data_ingestion_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'started'
    CHECK (status IN ('started','success','failed','partial')),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  rows_seen INTEGER NOT NULL DEFAULT 0,
  rows_inserted INTEGER NOT NULL DEFAULT 0,
  rows_updated INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_job_started
  ON data_ingestion_runs (job_name, started_at DESC);


CREATE TABLE IF NOT EXISTS mcp_tool_audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tool_name TEXT NOT NULL,
  caller TEXT NOT NULL DEFAULT 'unknown',
  request_summary TEXT,
  entity_type TEXT,
  entity_id TEXT,
  action_type TEXT NOT NULL DEFAULT 'read'
    CHECK (action_type IN ('read','write','draft','admin')),
  success BOOLEAN NOT NULL DEFAULT TRUE,
  error TEXT,
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mcp_audit_tool_created
  ON mcp_tool_audit_log (tool_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_mcp_audit_action_created
  ON mcp_tool_audit_log (action_type, created_at DESC);


CREATE OR REPLACE FUNCTION match_documents(
  query_embedding vector(1536),
  match_count INT DEFAULT 8,
  filter_type TEXT DEFAULT NULL,
  max_sensitivity TEXT DEFAULT 'confidential'
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
