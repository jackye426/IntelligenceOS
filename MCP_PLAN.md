# DocMap Intelligence OS - MCP + Data Pipeline Plan

**Overall Progress:** `83%` (5 / 6 steps complete)

---

## TLDR

Keep the current web app stable, but make the main internal intelligence interface a hosted MCP server backed by Supabase and pgvector. A separate Python data-worker ingests and refreshes source data. Claude Desktop connects to the hosted MCP endpoint and can search DocMap knowledge, retrieve clinic and practitioner status, inspect content and appointment availability, and later create Gmail drafts for human review.

The plan is intentionally staged:

1. Secret hygiene and schema foundation.
2. Read-only MCP tools first.
3. Data ingestion lanes one at a time.
4. Privileged write tools, such as Gmail draft creation, only after auth, audit logging, and citations are working.

---

## Critical Decisions

- **Hosted MCP, not local** - Railway web service with HTTP/SSE or Streamable HTTP transport, so the team connects via a shared hosted URL instead of installing local code.
- **Authentication required** - every MCP request must require an auth token or OAuth-compatible protection. Validate allowed origins for browser-capable transports. Do not expose an unauthenticated hosted MCP endpoint.
- **Python for MCP and data-worker** - the reusable code is mostly Python and lives under existing project folders.
- **pgvector as the vector store** - Supabase Postgres stores embeddings in `document_embeddings`; `match_documents` performs similarity search.
- **Short cited chunks, not raw documents** - tools may return small relevant snippets and source metadata. They must not return entire email threads, patient conversations, call transcripts, or private files.
- **Entity scoping** - all embedded chunks include `entity_type`, source metadata, sensitivity, and ownership metadata so tools can scope retrieval.
- **Gmail drafts are phase 2** - start read-only. Add `draft_outreach_email` only after auth, audit logs, and human-review guardrails are in place.
- **Single Supabase instance initially** - web app, MCP server, and worker share Supabase. Prefer service-specific keys later.
- **Production secrets are not stored in the repo** - local dev uses `.env.local`; production uses Railway/Vercel secret managers.

---

## Corrected Reuse Map

| Capability | Existing path confirmed in this repo | Use |
|---|---|---|
| Doctor outreach Python package | `Doctors Sales Agent/outreach_agent/` | Gmail, practitioner, prompt, and outreach logic |
| Doctor outreach scripts/tests | `Doctors Sales Agent/scripts/`, `Doctors Sales Agent/tests/` | Reference for Supabase upload and expected behavior |
| HCA monitor | `Appointment utilization rate/hca-monitor/` | Appointment scrape and scheduler patterns |
| HCA SQLite DB | `Appointment utilization rate/hca-monitor/data/hca_monitor.db` | One-time migration source for appointment tables |
| TikTok/social data | `Social media analysis/tiktok_analysis/` | Transcript/comment/catalog ingestion |
| Content tracker CSV | `Social media analysis/Marketing - Content - Tracker - Content Tracker (3).csv` | Content performance ingestion |
| Clinic sales data | `Clinic sales agent/output/clinic_sales_results.csv` | Optional clinic seed/enrichment data |
| Existing TS embeddings pattern | `worker/handlers/embed-document.ts` | Reference for OpenRouter embeddings |
| Existing pgvector SQL | `sql/002_embeddings.sql` | To be extended by `sql/004_mcp_sources.sql` |

Do not use the older unqualified paths from the previous plan, such as `outreach_agent/...`, `hca-monitor/...`, `tiktok_analysis/...`, or `Total conversation/...`, unless those paths are created deliberately.

---

## Tasks

- [x] **Step 0: Secret Hygiene and Repo Safety**
  - [x] Keep real local secrets in `.env.local` only.
  - [x] Keep `.env` and `.env.example` placeholder-only.
  - [x] Confirm `.gitignore` ignores `.env.local`, `.env.*.local`, credential JSON files, token files, private keys, build outputs, and scratch files.
  - [ ] Rotate any Supabase, database, OpenRouter, or Google credentials that were previously exposed in `.env`, chat, screenshots, or copied files.

- [x] **Step 1: Supabase Schema**
  - [ ] Run existing migrations in order if not already applied: `001_clinic_intelligence.sql`, `002_embeddings.sql`, `003_doctor_outreach.sql`.
  - [ ] Run `sql/004_mcp_sources.sql`.
  - [x] Confirm `document_embeddings` now has citation metadata, sensitivity metadata, and chunk fields.
  - [x] Confirm `match_documents` returns only short chunks plus metadata.
  - [x] Confirm metadata tables exist: `email_threads`, `patient_conversations`, `call_transcripts`, `content_posts`, `appointment_slots`, `booking_guids`, `mcp_tool_audit_log`, `data_ingestion_runs`.

- [x] **Step 2: Historical Data Ingestion**
  - [x] Start with one low-risk lane: content tracker ingestion.
  - [x] Add `scripts/ingest-content-tracker.py` to parse `Social media analysis/Marketing - Content - Tracker - Content Tracker (3).csv`.
  - [x] Upsert rows into `content_posts`.
  - [x] Chunk captions/transcripts/comments separately and insert embeddings into `document_embeddings`.
  - [x] Next add TikTok transcript/comment ingestion from `Social media analysis/tiktok_analysis/`.
  - [x] Next add HCA SQLite migration from `Appointment utilization rate/hca-monitor/data/hca_monitor.db`.
  - [ ] Add patient conversation and Gmail ingestion only after privacy review.

- [x] **Step 3: Data Worker Service**
  - [x] Scaffold `data-worker/` as a Python package.
  - [x] Use APScheduler for scheduled jobs.
  - [x] Add `data_ingestion_runs` logging for every job start, success, failure, and row count.
  - [x] Implement idempotent upserts using source IDs and content hashes.
  - [ ] Deploy to Railway as a background worker only after local dry runs pass.

- [x] **Step 4: Read-Only MCP Server**
  - [x] Scaffold `mcp-server/` as a Python package.
  - [x] Require `MCP_AUTH_TOKEN` on every request.
  - [x] Enforce `MCP_ALLOWED_ORIGINS` where relevant.
  - [x] Add audit logging to `mcp_tool_audit_log` for every tool call.
  - [x] Implement read-only tools first:
    - [x] `search_knowledge`
    - [x] `search_practitioners`
    - [x] `get_practitioner_status`
    - [x] `get_clinic_briefing`
    - [x] `get_patient_demand_patterns`
    - [x] `get_content_performance`
    - [x] `get_appointment_availability`
    - [x] `get_weekly_briefing`

- [ ] **Step 5: Privileged MCP Tools**
  - [ ] Add `draft_outreach_email` only after read-only MCP is stable.
  - [ ] Require explicit confirmation input before creating a Gmail draft.
  - [ ] Store Gmail draft creation events in `mcp_tool_audit_log`.
  - [ ] Return Gmail draft ID and source citations; never send emails automatically.

- [x] **Step 6: Team Onboarding and Operations**
  - [x] Write `docs/mcp_team_setup.md`.
  - [x] Write `docs/mcp_prompt_guide.md`.
  - [x] Document Railway service URLs and environment variables outside the repo, or in a redacted internal doc.
  - [x] Add runbook sections for key rotation, failed worker jobs, embedding backfills, and disabling privileged tools.

---

## Out of Scope

- New web app product features.
- Automated email sending.
- Patient chat routing or notifications.
- Broad patient-data access without privacy review.
- Unauthenticated hosted MCP access.

---

## New paths added in this build

```text
data-worker/
mcp-server/
scripts/ingest-content-tracker.py
scripts/ingest-tiktok.py
scripts/ingest-hca-sqlite.py
scripts/test-embed.py
docs/mcp_team_setup.md
docs/mcp_prompt_guide.md
docs/mcp_runbook.md
```
