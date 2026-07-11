-- Relationship Desk schema
--
-- Run after 004_mcp_sources.sql.
-- Safe to re-run: uses CREATE TABLE IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS relationship_contacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  display_name TEXT,
  email TEXT,
  organization TEXT,
  contact_type TEXT NOT NULL DEFAULT 'other'
    CHECK (contact_type IN ('practitioner','clinic','partner','internal','other')),
  linked_entity_type TEXT,
  linked_entity_id TEXT,
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_relationship_contacts_email
  ON relationship_contacts (lower(email))
  WHERE email IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_relationship_contacts_linked
  ON relationship_contacts (linked_entity_type, linked_entity_id);


CREATE TABLE IF NOT EXISTS relationship_chases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contact_id UUID REFERENCES relationship_contacts (id) ON DELETE SET NULL,
  gmail_thread_id TEXT,
  account_email TEXT,
  objective TEXT NOT NULL,
  why_it_matters TEXT,
  needed_response TEXT,
  status TEXT NOT NULL DEFAULT 'needs_chase'
    CHECK (status IN (
      'needs_first_touch','waiting','needs_chase','drafted','sent',
      'replied','done','paused'
    )),
  next_action TEXT,
  next_chase_due_at TIMESTAMPTZ,
  last_contacted_at TIMESTAMPTZ,
  last_reply_at TIMESTAMPTZ,
  chase_count INTEGER NOT NULL DEFAULT 0,
  urgency TEXT NOT NULL DEFAULT 'normal'
    CHECK (urgency IN ('low','normal','high')),
  safety_level TEXT NOT NULL DEFAULT 'uncertain'
    CHECK (safety_level IN ('safe','uncertain','risky')),
  send_mode TEXT NOT NULL DEFAULT 'requires_approval'
    CHECK (send_mode IN ('draft_only','can_send_if_safe','requires_approval')),
  owner TEXT NOT NULL DEFAULT 'jack',
  notes TEXT,
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_relationship_chases_status_due
  ON relationship_chases (status, next_chase_due_at);

CREATE INDEX IF NOT EXISTS idx_relationship_chases_thread
  ON relationship_chases (gmail_thread_id);

CREATE INDEX IF NOT EXISTS idx_relationship_chases_contact
  ON relationship_chases (contact_id);


CREATE TABLE IF NOT EXISTS relationship_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  chase_id UUID REFERENCES relationship_chases (id) ON DELETE CASCADE,
  event_type TEXT NOT NULL
    CHECK (event_type IN (
      'created','drafted','sent','replied','marked_waiting',
      'marked_done','snoozed','note','updated'
    )),
  gmail_message_id TEXT,
  gmail_draft_id TEXT,
  summary TEXT,
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by TEXT NOT NULL DEFAULT 'relationship_desk'
);

CREATE INDEX IF NOT EXISTS idx_relationship_events_chase_created
  ON relationship_events (chase_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_relationship_events_type_created
  ON relationship_events (event_type, created_at DESC);

