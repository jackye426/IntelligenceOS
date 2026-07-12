# Relationship Desk MCP

Relationship Desk is a separate MCP service for Gmail relationship memory, chase tracking, draft creation, and supervised sending.

It deliberately sits outside the marketing Intelligence OS MCP. Marketing tools stay read-heavy; Relationship Desk owns inbox memory and Gmail actions.

## What It Does

- tracks who needs chasing and why
- remembers the needed response, next chase date, and current status
- searches and briefs Gmail threads
- builds evidence-led relationship context briefs
- drafts routine follow-ups
- creates Gmail drafts
- sends only when the configured mode and safety rules allow it
- syncs replies back into chase state
- reads approved Intelligence OS context through configured tables

## Claude Tool Guide

Use these tools in this order when possible:

```text
relationship_desk_tool
- Best first tool for vague instructions.
- Examples: "Who do we need to chase?", "Draft all due chases", "Chase Sarah about the intro."

review_due_chases_tool
- Best for: "who still needs chasing?", "what is due today?"
- Returns open chase items due now.

list_chases_tool
- General chase search by status, due date, or open/done state.

capture_chase_tool
- Create a tracked chase from minimal direction.
- Use when the user says "chase X about Y" or "remind me to follow up with X".

search_threads_tool
- Search Gmail with Gmail query syntax before linking a chase to a thread.

get_thread_brief_tool
- Read a known Gmail thread before drafting or summarizing context.

get_relationship_context_tool
- Best for: "what do we know about this person?", pre-call prep, and judgement-heavy drafting.
- Combines chase/contact state, relationship events, lightweight memory, and live Gmail context.
- Returns `context_quality`, missing evidence, open loops, timeline, source list, and drafting guidance.
- If context is email-only or sparse, do not invent meeting details.

draft_chase_tool
- Generate follow-up copy only. Does not touch Gmail.
- Returns relationship context alongside the draft so Claude can see evidence quality.

act_on_chase_tool
- Creates a Gmail draft or sends, depending on RELATIONSHIP_DESK_MODE and safety.
- Use action="draft" by default.
- Use action="send" only when the user explicitly asks to send.
- Use action="send_if_safe" for "send the safe ones".

sync_replies_tool
- Checks tracked Gmail threads and marks chases as replied when a response arrives.

review_inbox_since_tool
- Reviews recent inbox threads and suggests which ones may need tracking.

scan_inbox_for_followups_tool
- Scans recent Gmail inbox threads, classifies likely follow-up needs, and creates suggested candidates.
- Does not send email.
- By default does not create chases unless a candidate is accepted.

review_followup_candidates_tool
- Lists suggested follow-ups found by inbox scans.

accept_followup_candidate_tool
- Converts a suggested follow-up into a tracked chase.

ignore_followup_candidate_tool
- Marks noisy or irrelevant suggestions as ignored.

get_relationship_brief_tool
- Shows chase, contact, and event history before calls or judgement-heavy replies.
- Use `get_relationship_context_tool` for fuller source-aware context.

mark_waiting_tool / snooze_chase_tool / mark_done_tool
- Update chase lifecycle after human review or after a draft/send.
```

## Safety Modes

```text
draft_only
- Never sends.
- act_on_chase_tool creates Gmail drafts only.

supervised_send
- Sends only when confirmed=true and the user explicitly approved sending.

auto_send_safe
- Sends routine safe follow-ups.
- Risky or unclear messages become drafts.
```

The default is `draft_only`.

## Shared Context

The practitioner context table is configurable:

```text
SUPABASE_PRACTITIONERS_TABLE=integrated_practitioners
```

This avoids hardcoding a stale practitioner table. If the canonical table changes, change the environment variable instead of the code.

## Local Run

```bash
cd relationship-desk-mcp
pip install -r requirements.txt
python main.py
```

## Required Env

```text
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
RELATIONSHIP_DESK_AUTH_TOKEN
RELATIONSHIP_GMAIL_CLIENT_ID
RELATIONSHIP_GMAIL_CLIENT_SECRET
RELATIONSHIP_GMAIL_REFRESH_TOKEN
RELATIONSHIP_GMAIL_ACCOUNT_EMAIL
RELATIONSHIP_DESK_MODE=draft_only|supervised_send|auto_send_safe
```

Run `sql/006_relationship_desk.sql` before using chase-state tools.
Run `sql/007_relationship_followup_candidates.sql` before using inbox candidate tools.
Run `sql/008_relationship_context_memory.sql` before using context memory tools.

## Context Memory Policy

Relationship Desk stores lightweight memory and source references, not raw inbox or transcript archives by default.

Store:

```text
contact ids
source ids: gmail_thread_id, calendar_event_id, drive_file_id
dates, titles, participants
short summaries
open loops / commitments
context quality
```

Avoid storing by default:

```text
full email bodies
full transcripts
attachments
patient-sensitive content
```

Use context quality labels literally:

```text
rich          email + meeting/docs/transcript-style evidence
good          email plus at least one other source or active memory
email-only    Gmail/chase evidence only
calendar-only meeting metadata only
sparse        contact exists but little context
unknown       unresolved or no evidence
```

## Worker

The MCP is the interactive action layer. The optional worker keeps inbox state warm in the background:

```bash
cd relationship-desk-mcp
python worker.py
```

Schedule:

```text
sync_replies: every 30 minutes
scan_inbox_for_followups: every 2 hours at minute 10
```

Worker env:

```text
RELATIONSHIP_WORKER_RUN_ON_START=false
RELATIONSHIP_WORKER_AUTO_CONVERT=false
RELATIONSHIP_WORKER_SCAN_HOURS_BACK=96
RELATIONSHIP_WORKER_SCAN_MAX_RESULTS=50
RELATIONSHIP_WORKER_MIN_CONFIDENCE=0.65
RELATIONSHIP_WORKER_SYNC_LIMIT=100
```

Keep `RELATIONSHIP_WORKER_AUTO_CONVERT=false` until the candidate quality is proven.
