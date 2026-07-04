# Execution Plan — Close-out Sprint (2026-07-04)

**Overall Progress:** `17%` (Step 2 done)

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

- [ ] 🟥 **Step 3: Git hygiene for generated pipeline data**
  - [ ] 🟥 Find and remove the remaining write to legacy `Social media analysis/tiktok_analysis/data/docmap_catalog_*.json` (write only to `marketing-pipeline/tiktok/data/catalog/`)
  - [ ] 🟥 Commit current pipeline output churn (6 modified data files) as a data-refresh commit
  - [ ] 🟥 Verify a fresh `tiktok refresh` run leaves the legacy dir untouched; `pytest marketing-pipeline/tests/` green

- [ ] 🟥 **Step 4: P0 — Shared ingestion scaffold**
  - [ ] 🟥 Create `data/imports/` + `data/staging/` layout; add to `.gitignore`
  - [ ] 🟥 Scaffold `ingestion-pipeline/` package: `config.py` (paths from env), CLI entrypoint `python -m ingestion_pipeline`
  - [ ] 🟥 Staging envelope Pydantic model + JSONL read/write with dedupe by `source_id`
  - [ ] 🟥 Wire `shared/` modules: Supabase client, embeddings, hashing, chunking (reuse `data-worker/common/`), `ingestion_log`
  - [ ] 🟥 `review` subcommands (list/approve/reject on `review_queue.jsonl`)
  - [ ] 🟥 `sync all --dry-run` prints row counts without writing; runs log to `data_ingestion_runs`
  - [ ] 🟥 Add ingestion env vars to `.env.example`

- [ ] 🟥 **Step 5: P4 — Clinic sales CSV seed**
  - [ ] 🟥 Inspect `Clinic sales agent/output/clinic_sales_results.csv` columns; document mapping in `DATA_INGESTION_PLANS.md`
  - [ ] 🟥 `lanes/clinic_csv/parse.py` — CSV → staging envelope
  - [ ] 🟥 `sync/clinic_accounts.py` — upsert by website_url/name fuzzy match; skip manual-edit overwrites; embed summary (`entity_type=clinic_account`)
  - [ ] 🟥 CLI shim `scripts/ingest-clinic-sales-csv.py`; run once against Supabase
  - [ ] 🟥 Verify: rows visible in `/accounts`, re-import idempotent, `search_knowledge(entity_type=clinic_account)` finds them
  - [ ] 🟥 Check off MASTER_PLAN E2 + catalog A6 status

- [ ] 🟥 **Step 6: F1 — Vercel deploy prep + deploy**
  - [ ] 🟥 Verify local prod build passes (`next build`)
  - [ ] 🟥 Confirm `vercel.json` excludes worker/mcp/marketing-pipeline paths per `docs/DEPLOY.md`
  - [ ] 🟥 Import repo to Vercel, set env (`SUPABASE_*`, `OPENROUTER_*`, `SESSION_PASSWORD`) — *human*
  - [ ] 🟥 Verify: login works, accounts/pipeline/Ask DocMap load against prod Supabase
  - [ ] 🟥 Check off F1; update `STATUS.md` + `docs/DEPLOY.md` if steps drifted

## Not in this sprint

- P1–P3 ingestion lanes (transcripts, Gmail) — next sprint after P0 lands
- P5/P6 patient lanes — blocked on privacy review
- Instagram (Phase C), agent crons (E1), carousels, Playwright worker — per MASTER_PLAN deferrals
