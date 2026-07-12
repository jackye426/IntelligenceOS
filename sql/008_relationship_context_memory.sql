-- Relationship Desk lightweight context memory.
--
-- Run after 006_relationship_desk.sql.
-- Safe to re-run: uses CREATE TABLE IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS relationship_context_sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contact_id UUID REFERENCES relationship_contacts (id) ON DELETE SET NULL,
  source_type TEXT NOT NULL
    CHECK (source_type IN (
      'gmail_thread','gmail_message','calendar_event','drive_file',
      'call_transcript','manual_note','relationship_chase'
    )),
  source_id TEXT NOT NULL,
  source_url TEXT,
  title TEXT,
  occurred_at TIMESTAMPTZ,
  participants JSONB NOT NULL DEFAULT '[]',
  context_quality TEXT NOT NULL DEFAULT 'unknown'
    CHECK (context_quality IN (
      'rich','good','email-only','calendar-only','sparse','unknown'
    )),
  sensitivity TEXT NOT NULL DEFAULT 'internal'
    CHECK (sensitivity IN ('public','internal','confidential','restricted')),
  metadata JSONB NOT NULL DEFAULT '{}',
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_relationship_context_source UNIQUE (source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_relationship_context_sources_contact
  ON relationship_context_sources (contact_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_relationship_context_sources_type_seen
  ON relationship_context_sources (source_type, last_seen_at DESC);


CREATE TABLE IF NOT EXISTS relationship_memory_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contact_id UUID REFERENCES relationship_contacts (id) ON DELETE CASCADE,
  source_id UUID REFERENCES relationship_context_sources (id) ON DELETE SET NULL,
  memory_type TEXT NOT NULL
    CHECK (memory_type IN (
      'summary','open_loop','commitment','preference','risk',
      'decision','next_action','do_not_mention'
    )),
  content TEXT NOT NULL,
  evidence TEXT,
  confidence NUMERIC NOT NULL DEFAULT 0.5,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active','resolved','stale','dismissed')),
  occurred_at TIMESTAMPTZ,
  due_at TIMESTAMPTZ,
  sensitivity TEXT NOT NULL DEFAULT 'internal'
    CHECK (sensitivity IN ('public','internal','confidential','restricted')),
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_relationship_memory_items_contact_status
  ON relationship_memory_items (contact_id, status, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_relationship_memory_items_type
  ON relationship_memory_items (memory_type, status);
