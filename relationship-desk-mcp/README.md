# Relationship Desk MCP

Relationship Desk is a separate MCP service for Gmail relationship memory, chase tracking, draft creation, and supervised sending.

It deliberately sits outside the marketing Intelligence OS MCP. Marketing tools stay read-heavy; Relationship Desk owns inbox memory and Gmail actions.

## What It Does

- tracks who needs chasing and why
- remembers the needed response, next chase date, and current status
- searches and briefs Gmail threads
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

draft_chase_tool
- Generate follow-up copy only. Does not touch Gmail.

act_on_chase_tool
- Creates a Gmail draft or sends, depending on RELATIONSHIP_DESK_MODE and safety.
- Use action="draft" by default.
- Use action="send" only when the user explicitly asks to send.
- Use action="send_if_safe" for "send the safe ones".

sync_replies_tool
- Checks tracked Gmail threads and marks chases as replied when a response arrives.

review_inbox_since_tool
- Reviews recent inbox threads and suggests which ones may need tracking.

get_relationship_brief_tool
- Shows chase, contact, and event history before calls or judgement-heavy replies.

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
SUPABASE_PRACTITIONERS_TABLE=integrated_practitioner_with_phin
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
