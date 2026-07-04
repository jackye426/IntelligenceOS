# Execution Plan — Close-out Sprint (2026-07-04)

**Overall Progress:** `75%` (Steps 2–5 done; Step 6 awaits Vercel dashboard; Step 1 awaits key rotation)

## TLDR

Close the remaining gaps identified in the 2026-07-04 repo review: rotate exposed credentials (A1), commit and reconcile the planning docs, build the shared ingestion scaffold (P0) and the clinic sales CSV seed lane (P4), prep the Vercel deploy (F1), and stop generated pipeline data from churning the git working tree. Railway data-worker (A4) is confirmed live with runs in `data_ingestion_runs` — not in scope here.

## Critical Decisions

- **Keep pipeline data tracked in git (for now)** — `data-worker` first boot seeds `MARKETING_DATA_DIR` from GitHub `main` (see `docs/DEPLOY.md`), so untracking transcripts/catalog would break worker bootstrap. Hygiene = commit current churn + stop the duplicate legacy write path, not untracking.
- **Stop double-writes to `Social media analysis/tiktok_analysis/data/`** — B4 made legacy scripts thin wrappers but the legacy catalog path is still written on every run; single source of truth is `marketing-pipeline/tiktok/data/`.
- **P0 as `ingestion-pipeline/` package** — matches `marketing-pipeline` convention per `DATA_INGESTION_PLANS.md`; more than 3 lanes are planned so the package layout wins over `data-worker/ingestion/`.
- **P4 before P1–P3** — clinic CSV seed is the smallest unblocked lane, needs no OAuth or privacy review, and is immediately visible in the Next.js `/accounts` UI.
- **A1 rotation is human-executed** — key rotation happens in Supabase/OpenRouter/Google dashboards + Railway/Vercel secret managers; repo work is limited to verifying no secrets are tracked and updating `.env.local` after rotation.

## Tasks:

- [ ] 🟥 **Step 1: A1 — Credential rotation (human) + verification**
  - [ ] 🟥 Rotate Supabase service role key, OpenRouter API key, Google/Gmail credentials (dashboards) — *human*
  - [ ] 🟥 Update Railway (`mcp-server`, `data-worker`) and local `.env.local` with new keys — *human*
  - [ ] 🟥 Verify: `mcp.docmap.co.uk/health` OK, worker cron run succeeds post-rotation, old keys revoked
  - [ ] 🟥 Check off A1 in `MASTER_PLAN.md` + MCP_PLAN Step 0

- [x] 🟩 **Step 2: Commit docs + reconcile status files**
  - [x] 🟩 Commit `docs/DATA_SOURCES_CATALOG.md` + `docs/DATA_INGESTION_PLANS.md`
  - [x] 🟩 Reconcile `MASTER_PLAN.md`: A2 ✅ (tables verified via REST — 39 content_posts, 185 embeddings), A3 ✅ (/health 200), A4 ✅ (runs in `data_ingestion_runs`)
  - [x] 🟩 Update `STATUS.md` progress table + next steps

- [x] 🟩 **Step 3: Git hygiene for generated pipeline data**
  - [x] 🟩 Legacy write was `fetch_catalog(mirror_legacy=True)` default — flipped to `False` (opt-in for manual legacy scripts)
  - [x] 🟩 Committed pipeline output churn (6 data files) as data-refresh commit
  - [x] 🟩 `pytest marketing-pipeline/tests/` — 13/13 green; working tree clean

- [x] 🟩 **Step 4: P0 — Shared ingestion scaffold**
  - [x] 🟩 `data/imports/` + `data/staging/` created via config; gitignored (may contain PII)
  - [x] 🟩 `ingestion-pipeline/` package: `config.py`, `python -m ingestion_pipeline` CLI, installed editable
  - [x] 🟩 `StagingRecord` Pydantic envelope + JSONL merge deduped by `source_id` (hash change = update)
  - [x] 🟩 `shared/` modules mirrored from `data-worker/common` + `marketing_pipeline/shared` (hash-skip embeddings)
  - [x] 🟩 `review list|approve|reject` on `review_queue.jsonl`
  - [x] 🟩 `sync clinic-csv --dry-run` + `sync all --dry-run` print counts, no writes; live runs log to `data_ingestion_runs`
  - [x] 🟩 Ingestion env vars added to `.env.example`; tests 3/3 green

- [x] 🟩 **Step 5: P4 — Clinic sales CSV seed**
  - [x] 🟩 CSV inspected (44 cols, 1,831 rows; LLM columns empty); mapping documented in `DATA_INGESTION_PLANS.md`
  - [x] 🟩 `lanes/clinic_csv/parse.py` — skips 165 pre-filtered hospitals; Doctify URL fallback for NOT NULL website_url
  - [x] 🟩 `sync/clinic_accounts.py` — insert-only (name + Doctify-URL dedupe; no metadata column so manual edits always win); draft contacts; summary embeddings with retry/backoff
  - [x] 🟩 Imported: **1,662 accounts, 606 draft contacts, 1,663 embedding chunks** (first run hit a local DNS drop mid-batch; re-run + insert-only repair completed it; both runs in `data_ingestion_runs`)
  - [x] 🟩 Verified: re-run dry-run inserts 0 (idempotent); `match_documents(filter_type=clinic_account)` returns relevant clinics
  - [x] 🟩 MASTER_PLAN E2 + catalog A6 updated

- [ ] 🟨 **Step 6: F1 — Vercel deploy prep + deploy**
  - [x] 🟩 `next build` passes — all routes compile (static login, dynamic app/API routes)
  - [x] 🟩 Added `.vercelignore` excluding Python services + data dirs (`vercel.json` alone excluded nothing)
  - [ ] 🟥 Import repo to Vercel, set env (`SUPABASE_*`, `OPENROUTER_*`, `SESSION_PASSWORD`) — *human*
  - [ ] 🟥 Verify: login works, accounts/pipeline/Ask DocMap load against prod Supabase
  - [ ] 🟥 Check off F1; update `STATUS.md` + `docs/DEPLOY.md` if steps drifted

## Not in this sprint

- P1–P3 ingestion lanes (transcripts, Gmail) — next sprint after P0 lands
- P5/P6 patient lanes — blocked on privacy review
- Instagram (Phase C), agent crons (E1), carousels, Playwright worker — per MASTER_PLAN deferrals
