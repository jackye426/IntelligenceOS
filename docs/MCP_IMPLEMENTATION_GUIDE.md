# MCP Implementation Guide for a Less-Capable Executor

This guide is the execution version of `MCP_PLAN.md`. Follow it in order. Do not skip the security and schema steps.

## Ground Rules

- Do not print or commit secrets.
- Do not read `.env.local` unless explicitly asked.
- Do not put production keys in `.env`, `.env.example`, docs, SQL files, screenshots, or prompts.
- Keep the current web app stable. New work goes into `data-worker/`, `mcp-server/`, `scripts/`, `sql/`, and `docs/`.
- Start with read-only MCP tools. Add Gmail draft creation only after read-only tools, auth, and audit logs work.
- Return short cited chunks, not full raw documents.

## Current Repo Facts

Confirmed useful paths:

- Web app: `app/`, `components/`, `lib/`, `worker/`
- Existing clinic schema: `sql/001_clinic_intelligence.sql`
- Existing embeddings schema: `sql/002_embeddings.sql`
- Existing doctor outreach schema: `sql/003_doctor_outreach.sql`
- New MCP schema to run: `sql/004_mcp_sources.sql`
- Doctor Python package: `Doctors Sales Agent/outreach_agent/`
- HCA monitor: `Appointment utilization rate/hca-monitor/`
- HCA SQLite DB: `Appointment utilization rate/hca-monitor/data/hca_monitor.db`
- TikTok/social data: `Social media analysis/tiktok_analysis/`
- Content tracker CSV: `Social media analysis/Marketing - Content - Tracker - Content Tracker (3).csv`
- Clinic sales output: `Clinic sales agent/output/clinic_sales_results.csv`

Do not use old assumed paths like `outreach_agent/`, `hca-monitor/`, `tiktok_analysis/`, or `Total conversation/` at repo root.

## Phase 0 - Secret Hygiene

1. Confirm `.gitignore` exists and includes:
   - `.env.local`
   - `.env.*.local`
   - credential/token JSON files
   - private keys
   - `node_modules/`
   - `.next/`

2. Confirm `.env` and `.env.example` contain placeholders only.

3. Put real local development secrets into `.env.local`.

4. Store production secrets only in deployment service variables:
   - Vercel/Railway variables for app services
   - Railway variables for worker/MCP services
   - GitHub Actions secrets if CI/CD needs them

5. Rotate any key that was previously exposed in `.env`, chat, screenshots, or copied scratch files.

Acceptance check:

- `Get-Content .env` shows placeholders only.
- `.env.local` exists but is ignored by `.gitignore`.
- No production secret is present in docs or SQL files.

## Phase 1 - Supabase Schema

Run SQL in this exact order in Supabase SQL editor:

1. `sql/001_clinic_intelligence.sql`
2. `sql/002_embeddings.sql`
3. `sql/003_doctor_outreach.sql`
4. `sql/004_mcp_sources.sql`

Then verify these tables exist:

- `document_embeddings`
- `email_threads`
- `patient_conversations`
- `call_transcripts`
- `content_posts`
- `appointment_slots`
- `booking_guids`
- `data_ingestion_runs`
- `mcp_tool_audit_log`

Verify `document_embeddings` has these fields:

- `entity_type`
- `entity_id`
- `content`
- `embedding`
- `source_table`
- `source_title`
- `source_url`
- `chunk_index`
- `content_hash`
- `metadata`
- `sensitivity`
- `owner_scope`

Acceptance check:

- `match_documents(...)` returns cited chunks with `source_title`, `source_url`, `chunk_index`, `sensitivity`, and a shortened `content`.

## Phase 2 - Shared Python Foundation

Create:

```text
data-worker/
  requirements.txt
  Procfile
  main.py
  common/
    __init__.py
    config.py
    supabase_client.py
    openrouter_client.py
    chunking.py
    hashing.py
    ingestion_log.py
  jobs/
    __init__.py
```

`data-worker/requirements.txt` should include:

```text
apscheduler
httpx
openai
python-dotenv
supabase
pydantic
pandas
```

Add more only when required by a specific job.

`config.py` must read:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `OPENROUTER_API_KEY`
- `OPENROUTER_EMBEDDING_MODEL`

Do not hardcode secrets.

Implement helpers:

- `hashing.content_hash(text: str) -> str`
- `chunking.chunk_text(text: str, max_chars=2500, overlap=250) -> list[str]`
- `openrouter_client.embed_text(text: str) -> list[float]`
- `supabase_client.get_client()`
- `ingestion_log.start_run(job_name, metadata)`
- `ingestion_log.finish_run(run_id, status, counts, error=None)`

Acceptance check:

- A small local script can embed `"hello world"` and insert one test row into `document_embeddings` with source metadata.

## Phase 3 - First Ingestion Lane: Content Tracker

Create:

```text
scripts/ingest-content-tracker.py
```

Input:

```text
Social media analysis/Marketing - Content - Tracker - Content Tracker (3).csv
```

Behavior:

1. Read CSV with pandas.
2. Map columns defensively. Do not assume exact header names without checking.
3. For each row, derive:
   - `platform`
   - `platform_post_id`
   - `title`
   - `post_url`
   - `posted_at`
   - `topic`
   - `format`
   - `hook`
   - `caption`
   - `metrics`
   - `metadata`
4. Upsert into `content_posts`.
5. Build embedding text from title, hook, caption, transcript if present.
6. Chunk text.
7. Upsert chunks into `document_embeddings`:
   - `entity_type = 'content_post'`
   - `entity_id = content_posts.id`
   - `source_table = 'content_posts'`
   - `source_title = title`
   - `source_url = post_url`
   - `chunk_index = index`
   - `content_hash = sha256(chunk)`
   - `sensitivity = 'internal'`
   - `metadata = {'platform': platform, 'topic': topic}`
8. Log run to `data_ingestion_runs`.

Acceptance check:

- Running the script twice does not duplicate rows.
- `content_posts` has rows.
- `document_embeddings` has `content_post` chunks.
- `match_documents` can retrieve a content chunk.

## Phase 4 - Read-Only MCP Server

Create:

```text
mcp-server/
  requirements.txt
  Procfile
  main.py
  common/
    __init__.py
    config.py
    auth.py
    supabase_client.py
    openrouter_client.py
    audit.py
  tools/
    __init__.py
    search_knowledge.py
    get_content_performance.py
```

`mcp-server/requirements.txt` should include:

```text
mcp
httpx
openai
python-dotenv
supabase
pydantic
```

Auth requirements:

- Require `MCP_AUTH_TOKEN`.
- Reject requests without the token.
- If an Origin header is present, allow only origins listed in `MCP_ALLOWED_ORIGINS`.
- Never expose a hosted MCP endpoint without auth.

Tool 1: `search_knowledge`

Input:

- `query: str`
- `entity_type: str | None`
- `match_count: int = 5`

Behavior:

1. Embed query.
2. Call Supabase RPC `match_documents`.
3. Pass `filter_type = entity_type`.
4. Return:
   - short snippet
   - source title
   - source URL
   - entity type
   - entity ID
   - similarity
5. Log tool call to `mcp_tool_audit_log`.

Tool 2: `get_content_performance`

Input:

- `platform: str | None`
- `limit: int = 10`

Behavior:

1. Query `content_posts`.
2. Sort by a clear metric if available, otherwise by `posted_at desc`.
3. Return concise structured rows.
4. Log tool call.

Acceptance check:

- MCP server starts locally.
- Calling `search_knowledge("what content worked for endometriosis")` returns cited chunks.
- Calling `get_content_performance()` returns rows from `content_posts`.
- Every call creates one `mcp_tool_audit_log` row.

## Phase 5 - More Ingestion Lanes

Implement in this order:

1. TikTok transcripts and comments:
   - Inputs under `Social media analysis/tiktok_analysis/data/transcripts/`
   - Comments under `Social media analysis/tiktok_analysis/analysis/comments_labeled_*.json`
   - Catalog JSON under `Social media analysis/tiktok_analysis/data/docmap_catalog_*.json`
   - Entity types: `tiktok_transcript`, `tiktok_comment_batch`

2. HCA appointment availability:
   - Input SQLite: `Appointment utilization rate/hca-monitor/data/hca_monitor.db`
   - Upsert into `appointment_slots` and `booking_guids`
   - Add MCP tool `get_appointment_availability`

3. Clinic intelligence:
   - Existing tables from `001_clinic_intelligence.sql`
   - Add MCP tool `get_clinic_briefing`

4. Practitioner intelligence:
   - Existing table: `integrated_practitioner_with_phin`
   - Existing outreach tables from `003_doctor_outreach.sql`
   - Add MCP tools `search_practitioners` and `get_practitioner_status`

5. Gmail and patient conversations:
   - Do last because privacy and OAuth are higher risk.
   - Store metadata in `email_threads` and `patient_conversations`.
   - Store only chunked, redacted, sensitivity-tagged snippets in `document_embeddings`.

Acceptance check:

- Each lane is idempotent.
- Each lane writes to `data_ingestion_runs`.
- Each lane has at least one MCP query that proves the data is usable.

## Phase 6 - Privileged Gmail Draft Tool

Only start after read-only tools are stable.

Tool: `draft_outreach_email`

Requirements:

- Requires explicit input field `confirm_create_draft: true`.
- Uses Gmail credentials from Railway secrets only.
- Creates a Gmail draft, never sends email.
- Logs action as `action_type = 'draft'` in `mcp_tool_audit_log`.
- Returns:
  - Gmail draft ID
  - subject
  - short body preview
  - citations used

Do not implement automated sending.

Acceptance check:

- Without `confirm_create_draft: true`, tool refuses.
- With confirmation, tool creates a draft and logs the action.
- No send API is called.

## Phase 7 - Railway Deployment

Deploy two services:

1. `data-worker` as background worker.
2. `mcp-server` as web service.

Railway variables for `data-worker`:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `OPENROUTER_API_KEY`
- `OPENROUTER_EMBEDDING_MODEL`
- Gmail variables only when Gmail jobs are enabled.

Railway variables for `mcp-server`:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` or read-only equivalent
- `OPENROUTER_API_KEY`
- `OPENROUTER_EMBEDDING_MODEL`
- `MCP_AUTH_TOKEN`
- `MCP_ALLOWED_ORIGINS`
- Gmail variables only when draft tool is enabled.

Acceptance check:

- Railway logs show service startup.
- MCP endpoint rejects unauthenticated requests.
- MCP endpoint accepts authenticated requests.
- Read-only tools work against production Supabase.

## Phase 8 - Team Docs

Create:

```text
docs/mcp_team_setup.md
docs/mcp_prompt_guide.md
docs/mcp_runbook.md
```

Team setup doc must include:

- Hosted MCP URL placeholder, not secrets.
- Where to place auth token locally.
- How to test connection.

Prompt guide must include:

- Example practitioner search prompts.
- Example clinic briefing prompts.
- Example patient-demand prompts.
- Example content-performance prompts.
- How to ask for citations.

Runbook must include:

- How to rotate `MCP_AUTH_TOKEN`.
- How to disable Gmail draft tool.
- How to rerun ingestion.
- How to inspect failed `data_ingestion_runs`.
- How to backfill embeddings.

## Final Definition of Done

- Repo contains no real secrets.
- `MCP_PLAN.md` reflects actual repo paths.
- `sql/004_mcp_sources.sql` exists and runs after earlier SQL files.
- Content tracker ingestion works and is idempotent.
- Read-only MCP server works locally.
- `search_knowledge` returns cited chunks only.
- Every MCP tool call is logged.
- Hosted MCP requires auth.
- Gmail draft creation is not available until explicitly implemented as a later privileged tool.
