# DocMap Clinic Intelligence OS — Implementation Plan

**Overall Progress:** `100%` (10 / 10 steps complete)

---

## TLDR

Replace the static HTML prototype with a real Next.js + Supabase application. The core value unlock is a backend that can ingest clinic intelligence at scale — via Doctify scraping, clinic website crawling, and LLM-powered extraction — and surface it through the existing UI shell plus a new "Ask DocMap" internal chat interface.

---

## Critical Decisions

- **Next.js App Router** — React (user preference), API routes co-located, clean Vercel deployment path later
- **Supabase (existing project)** — hosted Postgres from day one; practitioners table already present; pgvector available for embeddings
- **Prisma** — ORM layer abstracts raw SQL, handles migrations, critical since Postgres is new territory
- **pg-boss** — Postgres-native job queue; Doctify scraping and website crawling are long-running and cannot run inside API route timeouts
- **Playwright** — required for Doctify (React SPA with intercepted JSON API); no lighter alternative works at scale
- **Cheerio + @mozilla/readability** — Node.js equivalent of Python's Trafilatura for clinic website text extraction
- **OpenRouter via OpenAI SDK** — same pattern already proven in the Python repo; model choice deferred
- **iron-session** — minimal shared-password auth; one env var, one login page, session cookie
- **pgvector** — embeddings stored in Supabase for "Ask DocMap" RAG; no separate vector DB needed
- **CQC lookup** — not in scope for this build; may be added later as a lightweight enrichment step
- **No automated email sending** — outreach drafts require human approval before leaving the system

---

## Tasks

- [x] 🟩 **Step 1: Project Scaffold**
  - [x] 🟩 Next.js (App Router, TypeScript) initialised; static MVP archived to `archive/static-mvp/`
  - [x] 🟩 All core dependencies installed: `@supabase/supabase-js`, `iron-session`, `openai`, `pg-boss`, `playwright`, `cheerio`, `@mozilla/readability`, `jsdom`
  - [x] 🟩 `.env` updated with slots for all required variables
  - [x] 🟩 Design system ported to `app/globals.css`
  - [x] 🟩 App shell layout with `Sidebar` component (client-side, active link highlighting)

- [x] 🟩 **Step 2: Auth**
  - [x] 🟩 `/login` page with password input and error state
  - [x] 🟩 `POST /api/auth/login` and `POST /api/auth/logout` route handlers
  - [x] 🟩 Middleware redirects all unauthenticated requests to `/login`

- [x] 🟩 **Step 3: Database Schema**
  - [x] 🟩 `sql/001_clinic_intelligence.sql` — all core tables with indexes and auto-updated `updated_at`
  - [x] 🟩 `sql/002_embeddings.sql` — pgvector extension, `document_embeddings` table, `match_documents` RPC function
  - [x] 🟩 Full TypeScript types in `types/database.ts`

- [x] 🟩 **Step 4: Core API Layer**
  - [x] 🟩 `GET/POST /api/accounts`
  - [x] 🟩 `GET/PATCH/DELETE /api/accounts/[id]` (soft delete)
  - [x] 🟩 `POST /api/accounts/[id]/interactions`
  - [x] 🟩 `POST /api/accounts/[id]/stage` with pipeline history logging
  - [x] 🟩 `GET/POST/PATCH /api/accounts/[id]/tasks`
  - [x] 🟩 `GET/POST /api/accounts/[id]/outreach` and `PATCH /api/accounts/[id]/outreach/[draftId]`

- [x] 🟩 **Step 5: UI Shell**
  - [x] 🟩 Accounts view — list + search + detail panel (contacts, observations, drafts, tasks, activity)
  - [x] 🟩 Pipeline view — kanban board, wired to real data
  - [x] 🟩 Research view — website research queue + Doctify scraper trigger + evidence ledger
  - [x] 🟩 Outreach view — draft composer, tone toggle, claim checks, approve button
  - [x] 🟩 localStorage removed; all state via Supabase API

- [x] 🟩 **Step 6: Background Job Infrastructure**
  - [x] 🟩 `lib/boss.ts` — pg-boss singleton with retry config
  - [x] 🟩 `worker/index.ts` — standalone worker with all handlers registered; graceful shutdown
  - [x] 🟩 `POST /api/jobs/research`, `POST /api/jobs/doctify`, `GET /api/jobs/status/[runId]`

- [x] 🟩 **Step 7: Doctify Scraper Pipeline**
  - [x] 🟩 `worker/handlers/doctify-scrape.ts` — Playwright browser, JSON API interception, DOM fallback
  - [x] 🟩 Pagination across listing pages (up to 50 pages per URL)
  - [x] 🟩 Upserts to `doctify_profiles`; auto-creates `clinic_accounts` and queues `website_research`

- [x] 🟩 **Step 8: Clinic Website Research Pipeline**
  - [x] 🟩 `worker/handlers/website-research.ts` — sitemap discovery + URL parsing
  - [x] 🟩 Fallback to homepage crawl if no sitemap; SSRF domain validation
  - [x] 🟩 Priority-ranked page fetching; Cheerio + Readability text extraction
  - [x] 🟩 Content-hash deduplication; stores to `clinic_sources`; queues `llm_extract`

- [x] 🟩 **Step 9: LLM Extraction + Outreach Generation**
  - [x] 🟩 `lib/llm/prompts.ts` — enrichment, judge, and outreach prompts (ported from Python repo)
  - [x] 🟩 `worker/handlers/llm-extract.ts` — enrichment call + judge pass + structured DB writes
  - [x] 🟩 `lib/llm/outreach.ts` — tone-aware outreach draft generation
  - [x] 🟩 Observations and contacts written with source citations; fit score and sales angle updated

- [x] 🟩 **Step 10: Ask DocMap (Internal RAG Chat)**
  - [x] 🟩 `worker/handlers/embed-document.ts` — OpenRouter embedding + upsert to pgvector
  - [x] 🟩 `POST /api/chat` — query embedding → `match_documents` RPC → LLM answer with citations
  - [x] 🟩 Ask DocMap view — chat UI with message history, source citation pills, suggested queries

---

## Out of Scope for This Build

- CQC registry lookup
- Automated email sending (drafts are human-approved only)
- Patient medical data ingestion
- Multi-user auth (per-user accounts, roles)
- Hosted deployment (local only until UI is validated)
