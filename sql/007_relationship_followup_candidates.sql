-- Relationship Desk follow-up candidate schema.
--
-- Run after 006_relationship_desk.sql.
-- Safe to re-run: uses CREATE TABLE IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS relationship_followup_candidates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  gmail_thread_id TEXT NOT NULL,
  gmail_message_id TEXT,
  contact_id UUID REFERENCES relationship_contacts (id) ON DELETE SET NULL,
  sender_email TEXT,
  sender_name TEXT,
  subject TEXT,
  classification TEXT NOT NULL
    CHECK (classification IN (
      'waiting_on_them','they_need_us','needs_review','no_action'
    )),
  reason TEXT NOT NULL,
  suggested_objective TEXT,
  suggested_needed_response TEXT,
  confidence NUMERIC NOT NULL DEFAULT 0,
  risk_level TEXT NOT NULL DEFAULT 'uncertain'
    CHECK (risk_level IN ('safe','uncertain','risky')),
  status TEXT NOT NULL DEFAULT 'suggested'
    CHECK (status IN ('suggested','accepted','ignored','converted','dismissed')),
  due_at TIMESTAMPTZ,
  detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  converted_chase_id UUID REFERENCES relationship_chases (id) ON DELETE SET NULL,
  evidence JSONB NOT NULL DEFAULT '{}',
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_relationship_followup_candidates_thread_active
  ON relationship_followup_candidates (gmail_thread_id)
  WHERE status IN ('suggested','accepted');

CREATE INDEX IF NOT EXISTS idx_relationship_followup_candidates_status_due
  ON relationship_followup_candidates (status, due_at);

CREATE INDEX IF NOT EXISTS idx_relationship_followup_candidates_confidence
  ON relationship_followup_candidates (confidence DESC);

CREATE INDEX IF NOT EXISTS idx_relationship_followup_candidates_contact
  ON relationship_followup_candidates (contact_id);


CREATE TABLE IF NOT EXISTS relationship_worker_state (
  key TEXT PRIMARY KEY,
  value JSONB NOT NULL DEFAULT '{}',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
