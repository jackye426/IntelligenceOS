# Intelligence OS — Master Completion Plan

**Created:** 2026-07-03  
**Status:** Active — single source of truth for all outstanding work  
**Repo:** [jackye426/IntelligenceOS](https://github.com/jackye426/IntelligenceOS)

---

## Executive summary

| Area | Milestones done | Outstanding |
|------|-----------------|-------------|
| TikTok marketing pipeline | M1 + M2 complete | M3 (legacy port, MCP tools, cron OCR) |
| MCP server | 10 read-only tools | 3 TikTok tools + `draft_outreach_email` + deploy |
| Data worker | Local cron wired | Railway deploy + prod paths + weekly refresh |
| Instagram / carousels | TikTok path done | Instagram module (fresh fetch); **carousels deferred** |
| Next.js clinic OS | `PLAN.md` 100% local | **Vercel app-only** (minimal prod) |
| Doctor / clinic agents | Data in Supabase | UI integration, Gmail MCP, WhatsApp cron |

**Execution model:** Complete phases **A → F** in order unless a task is marked **parallel** or **defer**. Update this file and `STATUS.md` as each todo is checked off.

---

## Pre-flight decisions (locked 2026-07-03)

| # | Decision | Choice |
|---|----------|--------|
| 1 | **Hosting topology** | **Two Railway services:** `mcp-server` + `data-worker` (separate deploys, shared Supabase env) |
| 2 | **Worker artifacts in prod** | **No content tracker CSV mount.** **No HCA SQLite** in prod (HCA code repurposed elsewhere later). Instagram will use **fresh fetch/API picks**, not a static CSV on the worker. |
| 3 | **Carousels (C5–C6)** | **Defer until after Phases A–F complete** — different workflow; requires heavy human supervision. Not in one-go scope. |
| 4 | **Gmail MCP** | **Draft-only** (`draft_outreach_email`). Never send. OAuth refresh token stored in **Railway service variables** (encrypted at rest); not in repo. |
| 5 | **Vercel scope (minimal prod)** | **Next.js app only** on Vercel (auth, accounts, research, pipeline, outreach, Ask DocMap). **No Playwright worker on Vercel** — Doctify scrape jobs stay local/deferred until a dedicated Railway worker is needed. MCP + ingestion cron stay on Railway. |

**Recommended Railway layout**

```
Railway project: IntelligenceOS
├── service: mcp-server     (web, port 8000, MCP_AUTH_TOKEN)
└── service: data-worker    (worker, cron — TikTok pipeline only in prod)
```

**Vercel layout (minimal)**

```
Vercel project: intelligence-os-app
├── Next.js (app/, lib/, API routes)
├── Env: SUPABASE_*, OPENROUTER_*, SESSION_PASSWORD
└── Excludes: mcp-server, data-worker, marketing-pipeline cron, Playwright
```

---

## Completed (do not re-do)

### TikTok Milestone 1
- `marketing-pipeline` package: export, analyze, sync-supabase
- 39 videos → `content_posts` + embeddings
- MCP: `get_tiktok_marketing_insights`

### TikTok Milestone 2 (2026-07-03)
- OCR: 33/39 on-screen hooks (`google/gemini-3-flash-preview`)
- Comments: `refresh-comments` → 48 videos, 505 comments → digest embeddings
- Playbooks: import + `sync-playbooks` → `marketing_playbook` embeddings
- Legacy: `compile_complete_transcripts.py` reads `comments_raw/` by default
- MCP: `get_tiktok_content_briefing`
- Cron: `refresh-comments` → `export` → `sync-supabase` → `sync-playbooks`

### MCP Plan (~83%)
- Steps 0–4, 6: schema, ingestion lanes, read-only tools, docs/runbooks

### Next.js (`PLAN.md`)
- Clinic OS MVP: auth, accounts, research, pipeline, outreach, Ask DocMap (local)

---

## Phase A — Ops & production deploy

**Goal:** Secure credentials, confirm schema, ship MCP + data-worker to Railway.

| ID | Task | Status | Complexity | Key files | Acceptance |
|----|------|--------|------------|-----------|------------|
| A1 | Rotate exposed Supabase / OpenRouter / Google credentials | ⬜ | S | `MCP_PLAN.md` Step 0 | New keys in Railway + `.env.local`; old keys revoked |
| A2 | Confirm SQL 001–004 applied in prod Supabase | ✅ 2026-07-04 | S | `sql/001`–`004` | Tables + `match_documents` exist; spot-check row counts |
| A3 | Deploy `mcp-server` to Railway | ✅ | M | `mcp-server/Procfile`, `main.py` | `/health` 200; auth required; team can connect Claude Desktop |
| A4 | Deploy `data-worker` to Railway (TikTok cron only in prod) | ✅ 2026-07-04 | M | `data-worker/Procfile`, `main.py` | Cron runs TikTok pipeline; logs to `data_ingestion_runs` |
| A5 | Prod worker config: disable CSV/HCA jobs | ✅ | S | `data-worker/main.py`, `common/config.py` | `SKIP_CONTENT_TRACKER`, `SKIP_HCA` env flags; TikTok jobs only |

**Implementation notes (A3–A5):**
- MCP env: `SUPABASE_*`, `OPENROUTER_API_KEY`, `MCP_AUTH_TOKEN`, `MCP_ALLOWED_ORIGINS`
- Worker build: `pip install -e ./marketing-pipeline` from monorepo root
- Worker prod cron: **TikTok only** (`refresh-comments` → `export` → `sync-supabase` → `sync-playbooks`)
- **Do not mount** content tracker CSV or `hca_monitor.db` on Railway
- Gmail tokens (Phase D): `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` on **mcp-server** Railway service
- Document URLs in `docs/mcp_team_setup.md`

---

## Phase B — TikTok Milestone 3

**Goal:** Remove legacy subprocess dependence; complete MCP TikTok surface; automate weekly OCR.

| ID | Task | Status | Complexity | Key files | Acceptance |
|----|------|--------|------------|-----------|------------|
| B1 | Port `fetch_docmap_catalog` → `fetch_catalog` (live fetch) | ✅ | M | `stages/fetch_catalog.py` | Package fetch; legacy `--skip-catalog` |
| B2 | Port yt-dlp stats + Whisper transcribe from `run_pipeline.py` | ✅ | L | `stages/refresh_stats.py`, `transcribe_video.py`, `refresh_videos.py` | New videos get `*_COMPLETE.txt` + per-video JSON |
| B3 | Port master compile → `write_master_transcripts.py` | ✅ | M | `stages/write_master_transcripts.py` | `ALL_COMPLETE_TRANSCRIPTS.txt` built from package only |
| B4 | Retire legacy refresh subprocess shims | ✅ | S | `orchestrator.py`, `refresh_legacy.py`, `refresh_docmap.py`, `data-worker/main.py` | Package stages in-process; legacy scripts are thin wrappers |
| B5 | MCP `find_ab_tests` | ✅ | S | `mcp-server/tools/find_ab_tests.py` | Filtered A/B pairs from `content_posts.metadata` |
| B6 | MCP `suggest_next_tiktok_angles` | ✅ | S | `mcp-server/tools/suggest_next_tiktok_angles.py` | Ranked angles from comment analysis |
| B7 | Schedule weekly full refresh + OCR in data-worker | ✅ | S | `data-worker/main.py` | Weekly Sun 02:00 UTC: full refresh + OCR |
| B8 | `sql/005_tiktok_marketing.sql` (optional) | ⬜ defer | M | `sql/005_tiktok_marketing.sql` | Only if JSONB query pain on `metadata.ab_pairs` |

**Legacy vs ported (current):**

| Stage | State |
|-------|-------|
| Catalog fetch | Ported (`fetch_catalog`) |
| yt-dlp stats + Whisper | Ported (`refresh_stats`, `transcribe_video`, `refresh_videos`) |
| Master compile | Ported (`write_master_transcripts`; legacy script is thin wrapper) |
| Comments, OCR, hooks, A/B, sync | Ported |
| Playbooks | Ported |

**B5/B6 implementation:** Thin wrappers — logic already in `get_tiktok_marketing_insights.py` (`_aggregate_ab_tests`, `suggested_angles`). Add query params: `since`, `min_views`, `hook_source`, `limit`.

---

## Phase C — Instagram (fresh fetch; no CSV in prod)

**Goal:** Instagram ingestion via fresh picks/API — not static CSV on Railway. Carousels are **out of scope** until after Phase F.

| ID | Task | Status | Complexity | Key files | Acceptance |
|----|------|--------|------------|-----------|------------|
| C1 | One-time local CSV ingest (optional, dev only) | ⬜ optional | S | `scripts/ingest-content-tracker.py` | Run locally if historical IG rows needed in Supabase |
| C2 | Scaffold `marketing-pipeline/instagram/` with **fresh fetch** | ⬜ | L | `instagram/orchestrator.py`, `stages/fetch_posts.py` | New IG posts ingested without prod CSV |
| C3 | Instagram `export` + `sync-supabase` | ⬜ | M | `instagram/sync/supabase.py` | `content_posts` with `platform=instagram` from live source |
| C4 | Wire instagram job into data-worker (post-C3) | ⬜ | S | `data-worker/jobs/instagram.py` | Cron after TikTok job |
| C5 | Carousel V2 → Supabase | ⬜ **defer** | L | `Carousel agents V2/` | After A–F; supervised separately |
| C6 | Carousel MCP extensions | ⬜ **defer** | M | `get_content_performance.py` | With C5 |
| C7 | Marketing UI in Next.js | ⬜ **defer** | L | `app/(app)/marketing/` | Product decision |

**Note:** Retire prod dependence on `CONTENT_TRACKER_CSV`. Local CSV path remains for dev/bootstrap only.

---

## Phase D — MCP completion

**Goal:** Finish MCP plan Step 5; optional Ask DocMap bridge.

| ID | Task | Status | Complexity | Key files | Acceptance |
|----|------|--------|------------|-----------|------------|
| D1 | `draft_outreach_email` MCP tool (**draft only, never send**) | ✅ | L | `mcp-server/tools/draft_outreach_email.py` | Gmail draft created; draft ID returned |
| D2 | Human-confirm guardrail for D1 | ✅ | S | Tool schema | `confirmed: true` required |
| D3 | Gmail OAuth via Railway secrets on **mcp-server** | ✅ code | M | `mcp-server/common/gmail_draft.py` | Set `GMAIL_*` on Railway deploy |
| D4 | Update `docs/mcp_prompt_guide.md` + runbook | ✅ | S | docs | Draft-only rules documented |
| D5 | Patient/Gmail conversation ingestion | ⬜ defer | L | `MCP_PLAN.md` Step 2 | Privacy review required |
| D6 | Ask DocMap → MCP tools (optional) | ⬜ defer | M | `app/api/chat/route.ts` | Architecture decision |

---

## Phase E — Agent integration

**Goal:** Connect siloed Python agents to scheduled jobs and (optionally) Next.js.

| ID | Task | Status | Complexity | Key files | Acceptance |
|----|------|--------|------------|-----------|------------|
| E1 | Schedule WhatsApp → Supabase sync | ⬜ | S | `Doctors Sales Agent/scripts/sync_whatsapp_and_history_to_supabase.py` | Weekly cron in data-worker |
| E2 | Ingest clinic sales CSV | ⬜ | M | `Clinic sales agent/output/clinic_sales_results.csv` | Script + optional `clinic_accounts` enrichment |
| E3 | Doctor outreach surface in Next.js (optional) | ⬜ defer | L | `app/(app)/practitioners/` | UI for `doctor_outreach` table |
| E4 | Unified outreach model (clinic vs doctor) | ⬜ defer | L | `app/api/accounts/`, Doctors agent | Product boundary decision |

---

## Phase F — App hosting (minimal prod)

**Goal:** Production Next.js on Vercel. Playwright/Doctify worker **not** in initial prod scope.

| ID | Task | Status | Complexity | Key files | Acceptance |
|----|------|--------|------------|-----------|------------|
| F1 | Deploy Next.js to Vercel | ⬜ deploy | M | `vercel.json` | App live with auth; see `docs/DEPLOY.md` |
| F2 | Playwright worker (Doctify scrape) | ⬜ **defer** | M | `worker/index.ts` | Local-only until dedicated Railway worker justified |
| F3 | CQC registry enrichment | ⬜ **defer** | M | `Clinic sales agent/src/cqc_lookup.py` | |
| F4 | Multi-user auth / roles | ⬜ **defer** | M | `iron-session` | Shared password OK for minimal prod |
| F5 | Refresh `docs/architecture.md` + deployment docs | ⬜ | S | docs | Documents Vercel + Railway split |

---

## Execution order (one-go runbook)

```
Phase A (Railway: MCP + worker)  ──► unblocks team MCP + TikTok cron
    │
    ├─► B5, B6 (after A3): quick MCP tools
    │
    ├─► B1–B4, B7: TikTok legacy port
    │
    ├─► D1–D4: Gmail draft MCP (tokens on mcp-server Railway)
    │
    ├─► C2–C4: Instagram fresh-fetch module (no CSV in prod)
    │
    ├─► E1–E2: Agent cron + clinic CSV
    │
    ├─► F1, F5: Vercel app + docs
    │
    └─► LATER: C5–C6 carousels (supervised), F2 Playwright worker
```

**Defer:** B8, C1 (optional local), C5–C7, D5–D6, E3–E4, F2–F4

**Post-plan phase (supervised):** Carousel ingest + MCP extensions

---

## Verification checklist (definition of “all done”)

- [ ] Two Railway services live: `mcp-server` + `data-worker` (TikTok cron only)
- [ ] Data-worker **does not** require CSV or HCA DB in prod
- [ ] `content_posts`: TikTok (39+) maintained by cron
- [ ] `tiktok refresh` runs without legacy subprocess
- [ ] MCP tools: `find_ab_tests`, `suggest_next_tiktok_angles`, `draft_outreach_email` registered
- [ ] Gmail draft MCP: draft-only, tokens in Railway secrets
- [ ] Weekly OCR + catalog refresh scheduled on worker
- [ ] Vercel: Next.js app reachable (minimal prod)
- [ ] `pytest marketing-pipeline/tests/` green
- [ ] `STATUS.md` updated; this plan todos checked off
- [ ] Changes pushed to `main` on GitHub
- [ ] **Not required for done:** carousels, Playwright worker, Instagram rows (until C2–C4)

---

## Reference documents

| Doc | Purpose |
|-----|---------|
| `STATUS.md` | Live operational snapshot |
| `MCP_PLAN.md` | MCP + ingestion original plan (83%) |
| `PLAN.md` | Next.js clinic OS (complete, local) |
| `.cursor/plans/tiktok_milestone_2_*.plan.md` | M2 archive (complete) |
| `docs/mcp_prompt_guide.md` | MCP tool usage for agents |
| `docs/mcp_runbook.md` | Ops + incident response |

---

## Progress log

| Date | Phase | Notes |
|------|-------|-------|
| 2026-07-03 | — | Master plan created. M1+M2 complete. |
| 2026-07-03 | Pre-flight | Locked: 2× Railway, no CSV/HCA in prod, carousels deferred, Gmail draft-only, Vercel app-only. |
| 2026-07-03 | B,D,A5 | MCP find_ab_tests, suggest_angles, draft_outreach_email; fetch_catalog; worker SKIP flags + weekly cron; DEPLOY.md |
| 2026-07-04 | A2–A4 | Verified: MCP live at `mcp.docmap.co.uk` (/health 200), data-worker on Railway logging to `data_ingestion_runs`, sql/001–004 tables confirmed (39 content_posts, 185 embeddings). Remaining: A1 rotation, Phase C/E, F1. See `docs/EXECUTION_PLAN_2026-07.md`. |
