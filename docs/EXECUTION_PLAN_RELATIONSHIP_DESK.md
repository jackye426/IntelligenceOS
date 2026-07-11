# Execution Plan - Relationship Desk

**Created:** 2026-07-12  
**Status:** Plan only - no implementation yet  
**Service shape:** Separate MCP/service in this repo  
**Working name:** Relationship Desk  

---

## TLDR

Relationship Desk is a separate MCP/service for inbox memory, chase tracking, and safe relationship follow-up.

The primary user experience should be minimal direction:

```text
"Chase Sarah about the clinic intro."
"Who do we still need to chase?"
"Draft all obvious follow-ups."
"Send the safe ones and leave anything uncertain as drafts."
```

The system should know:

```text
Who are we waiting on?
Why do we need a response?
What thread/contact does this relate to?
When did we last chase?
What should happen next?
Should it send, draft, or ask me?
```

---

## Boundary

Build this as a sibling service, not inside the marketing MCP.

```text
mcp-server/
  Marketing + Intelligence OS tools

relationship-desk-mcp/
  Gmail relationship tools
  chase memory
  draft/send policy
```

Why:

- Gmail touches private threads and real outbound communication.
- Marketing users should not accidentally trigger Gmail actions.
- Relationship Desk needs separate auth, env vars, audit posture, and instructions.
- It can still read approved Intelligence OS context from Supabase.

---

## Core Product Loop

Every chase should answer:

```text
Who?
Why?
Since when?
What do we need from them?
What is the suggested next action?
Can Relationship Desk send it, or should it save a draft?
```

Daily loop:

1. Sync recent Gmail activity.
2. Detect replies and update chase statuses.
3. List due/overdue chases.
4. Draft obvious follow-ups.
5. Send only safe/approved messages.
6. Save uncertain messages as drafts.
7. Set the next chase date.

---

## User Experience

### Reminder / Chase Queue

User:

```text
Who do we still need to chase?
```

Relationship Desk:

```text
Needs chasing today

1. Dr Sarah Ahmed
   Why: Waiting for confirmation that she is happy to be listed on DocMap.
   Last touch: Follow-up sent 8 days ago.
   Needed response: Yes/no on joining DocMap.
   Suggested action: Short nudge.
   Recommendation: Safe to send.

2. London Women’s Clinic
   Why: Need a decision-maker response about an intro call.
   Last touch: Initial outreach sent 12 days ago.
   Needed response: Book intro call or identify right contact.
   Suggested action: Softer follow-up with value reminder.
   Recommendation: Draft only.
```

### Minimal Direction

User:

```text
Chase Emma about intros.
```

System resolves:

- Which Emma?
- Which Gmail thread?
- What intros?
- What was last asked?
- When did we last email?
- Is it due?
- Is a routine chase safe to send?

If confidence is high: draft/send based on mode.  
If confidence is medium: create draft and explain uncertainty.  
If confidence is low: ask one short clarifying question.

---

## Service Modes

Use an environment variable:

```text
RELATIONSHIP_DESK_MODE=draft_only | supervised_send | auto_send_safe
```

### `draft_only`

- Read Gmail.
- Track chases.
- Create Gmail drafts.
- Never send.

### `supervised_send`

- Draft and update state freely.
- Send only when the human explicitly says send.
- Best starting production mode.

### `auto_send_safe`

- Can send routine safe chases.
- Drafts anything uncertain/high-risk.
- Requires strong audit logging and safety classification.

---

## Safety Policy

Safe to send only when all are true:

- Recipient is known.
- Existing relationship/thread exists or contact was explicitly provided.
- Objective is clear.
- Message is a routine chase/follow-up.
- No new factual, pricing, legal, medical, or clinical claims.
- No sensitive patient detail.
- Tone is neutral and low-pressure.
- No attachments.
- No new commitment on behalf of DocMap.
- Relationship mode allows sending.

Otherwise:

```text
save draft only
```

Dangerous actions:

```text
send_gmail_draft
archive_thread
apply_label
delete_draft
```

These should be unavailable in v1 or require explicit confirmation.

---

## Data Model

Add a new migration later, e.g.:

```text
sql/006_relationship_desk.sql
```

### `relationship_contacts`

```text
id
display_name
email
organization
contact_type: practitioner | clinic | partner | internal | other
linked_entity_type
linked_entity_id
metadata
created_at
updated_at
```

### `relationship_chases`

This is the core table.

```text
id
contact_id
gmail_thread_id
account_email
objective
why_it_matters
needed_response
status: needs_first_touch | waiting | needs_chase | drafted | sent | replied | done | paused
next_action
next_chase_due_at
last_contacted_at
last_reply_at
chase_count
urgency: low | normal | high
safety_level: safe | uncertain | risky
send_mode: draft_only | can_send_if_safe | requires_approval
owner
notes
metadata
created_at
updated_at
```

### `relationship_events`

Append-only activity log.

```text
id
chase_id
event_type: created | drafted | sent | replied | marked_waiting | marked_done | snoozed | note
gmail_message_id
gmail_draft_id
summary
metadata
created_at
created_by
```

### Existing tables to reuse

- `email_threads`
- `doctor_outreach`
- `clinic_accounts`
- `clinic_interactions`
- `integrated_practitioner_with_phin`
- `mcp_tool_audit_log`

---

## Folder Structure

```text
relationship-desk-mcp/
  main.py
  requirements.txt
  railway.toml
  common/
    auth.py
    audit.py
    config.py
    gmail_client.py
    gmail_draft.py
    instructions.py
    relationship_store.py
    supabase_client.py
  tools/
    relationship_desk.py
    search_threads.py
    get_thread_brief.py
    review_inbox_since.py
    list_chases.py
    review_due_chases.py
    capture_chase.py
    update_chase.py
    draft_chase.py
    act_on_chase.py
    sync_replies.py
    get_relationship_brief.py
    mark_waiting.py
    mark_done.py
    snooze_chase.py
```

---

## MCP Instructions

Relationship Desk needs its own server instructions:

```text
You are Relationship Desk, a relationship follow-up operator.
Your job is to understand inbox state, track chases, draft safe replies, and maintain relationship memory.

The human should be able to give minimal direction.
Resolve contacts, threads, objectives, and next actions from available context.

Never send email unless the configured mode allows it and the action passes safety checks.
If uncertain, create a draft or ask one short clarifying question.

Always keep chase state up to date:
- who we are waiting on
- why we need the response
- when to chase next
- what happened most recently
```

---

## Tool Design

### User-facing orchestrator

```text
relationship_desk(instruction, mode)
```

Examples:

```text
relationship_desk("Who do we still need to chase?")
relationship_desk("Chase Sarah about the clinic intro.")
relationship_desk("Draft all due chases.")
relationship_desk("Send the safe ones and save the rest as drafts.")
```

This tool should orchestrate the smaller tools internally.

### Atomic tools

```text
list_chases(status?, due_before?, contact_type?)
review_due_chases(limit?)
capture_chase(instruction, contact_hint?, thread_hint?)
get_relationship_brief(contact_id | email | gmail_thread_id)
get_thread_brief(gmail_thread_id)
search_threads(query, max_results)
review_inbox_since(since)
sync_replies(since?)
draft_chase(chase_id, tone?)
act_on_chase(chase_id, action=draft|send_if_safe|send_confirmed)
mark_waiting(chase_id, next_chase_due_at)
mark_done(chase_id, outcome)
snooze_chase(chase_id, until, reason?)
```

### Later tools

```text
send_gmail_draft
archive_thread
apply_label
delete_draft
```

Ship only after v1 proves reliable.

---

## Implementation Phases

### Phase 0 - Scaffold

Goal: Separate service that boots.

- [ ] Create `relationship-desk-mcp/`
- [ ] Copy MCP server/auth/audit/Supabase patterns
- [ ] Use separate env vars
- [ ] Add `/health`
- [ ] Add empty tool set and server instructions

Acceptance:

- [ ] Runs locally
- [ ] Separate auth token
- [ ] Separate Railway config

### Phase 1 - Schema

Goal: Relationship memory exists independent of Gmail.

- [ ] Add `sql/006_relationship_desk.sql`
- [ ] Create `relationship_contacts`
- [ ] Create `relationship_chases`
- [ ] Create `relationship_events`
- [ ] Add indexes for due date, status, email, Gmail thread

Acceptance:

- [ ] Can create/list/update chases without Gmail

### Phase 2 - Read-Only Gmail

Goal: Understand inbox and threads.

- [ ] Add Gmail readonly client
- [ ] `search_threads`
- [ ] `get_thread_brief`
- [ ] `review_inbox_since`
- [ ] Normalize messages into safe summaries
- [ ] Upsert `email_threads` metadata

Acceptance:

- [ ] Can summarize a thread
- [ ] Can detect recent replies
- [ ] Does not expose full private thread unless explicitly needed and allowed

### Phase 3 - Chase Queue

Goal: "Who do we still need to chase?"

- [ ] `capture_chase`
- [ ] `list_chases`
- [ ] `review_due_chases`
- [ ] `mark_waiting`
- [ ] `mark_done`
- [ ] `snooze_chase`

Acceptance:

- [ ] Daily queue shows who, why, last touch, needed response, next action
- [ ] Minimal instruction can create a chase

### Phase 4 - Drafting

Goal: Safe follow-up drafts.

- [ ] `draft_chase`
- [ ] `act_on_chase(action=draft)`
- [ ] Gmail draft creation
- [ ] Write relationship event
- [ ] Move chase to `drafted` or `waiting`

Acceptance:

- [ ] Creates Gmail drafts for due chases
- [ ] Never sends in draft-only mode
- [ ] Records draft ID and next chase date

### Phase 5 - Supervised Send

Goal: Send only when allowed.

- [ ] Add safety classifier
- [ ] `act_on_chase(action=send_confirmed)`
- [ ] Optional `send_if_safe`
- [ ] Explicit audit log for every send attempt

Acceptance:

- [ ] Human can say "send this"
- [ ] Unsafe/uncertain messages stay as drafts
- [ ] Sent messages update chase state

### Phase 6 - Orchestrator

Goal: Minimal direction works.

- [ ] `relationship_desk(instruction, mode)`
- [ ] Resolves contact/thread/chase
- [ ] Chooses list/draft/send/ask
- [ ] Returns concise action summary

Acceptance:

- [ ] "Who do we still need to chase?" returns due queue
- [ ] "Chase Sarah about intros" creates/drafts/sends depending on confidence and mode
- [ ] "Draft all obvious chases" creates drafts and reports uncertain items

### Phase 7 - Context Bridge

Goal: Share approved Intelligence OS context.

- [ ] Link practitioners from `doctor_outreach`
- [ ] Link clinics from `clinic_accounts`
- [ ] Read `clinic_interactions` where relevant
- [ ] Use `search_knowledge`-style embeddings only for approved snippets

Acceptance:

- [ ] Relationship brief can include relevant DocMap context
- [ ] Gmail service does not expose marketing tools or unrelated private data

---

## Env Vars

```text
RELATIONSHIP_DESK_AUTH_TOKEN
RELATIONSHIP_DESK_MODE=supervised_send
RELATIONSHIP_GMAIL_CLIENT_ID
RELATIONSHIP_GMAIL_CLIENT_SECRET
RELATIONSHIP_GMAIL_REFRESH_TOKEN
RELATIONSHIP_GMAIL_ACCOUNT_EMAIL
RELATIONSHIP_ALLOWED_SEND_DOMAINS
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
OPENROUTER_API_KEY
```

Optional:

```text
RELATIONSHIP_DEFAULT_CHASE_DAYS=5
RELATIONSHIP_MAX_AUTO_SEND_PER_RUN=10
RELATIONSHIP_MAX_THREAD_MESSAGES=20
```

---

## Railway

Add a new Railway service:

```text
Root Directory: relationship-desk-mcp
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'
Healthcheck: /health
```

Do not reuse the marketing MCP auth token.

---

## First Useful Version

The first useful version should ship:

- schema
- read-only Gmail search/thread brief
- manual chase creation
- list/review due chases
- draft due chases
- create Gmail draft
- no sending

Then immediately add supervised send once draft quality feels safe.

---

## Success Criteria

1. User can ask "Who do we still need to chase?" and get a useful queue.
2. User can give minimal direction and Relationship Desk can create a chase.
3. Relationship Desk remembers why each response matters.
4. Relationship Desk drafts routine chases with little input.
5. Relationship Desk never sends uncertain messages.
6. Replies update chase status.
7. Every draft/send/state change is auditable.

