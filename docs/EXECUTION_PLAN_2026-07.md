# Execution Plan — Close-out Sprint (2026-07-04)

**Overall Progress:** `83%` (Steps 2–6 prep done; A1 + Vercel deploy remain)

## TLDR

Close the remaining gaps identified in the 2026-07-04 repo review: rotate exposed credentials (A1), commit and reconcile the planning docs, build the shared ingestion scaffold (P0) and the clinic sales CSV seed lane (P4), prep the Vercel deploy (F1), and stop generated pipeline data from churning the git working tree. Railway data-worker (A4) is confirmed live with runs in `data_ingestion_runs`.

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
  - [x] 🟩 Reconcile `MASTER_PLAN.md`: A2 ✅, A3 ✅, A4 ✅
  - [x] 🟩 Update `STATUS.md` progress table + next steps

- [x] 🟩 **Step 3: Git hygiene for generated pipeline data**
  - [x] 🟩 Legacy write was `fetch_catalog(mirror_legacy=True)` default — flipped to `False`
  - [x] 🟩 Committed pipeline output churn (6 data files) as data-refresh commit
  - [x] 🟩 `pytest marketing-pipeline/tests/` — 13/13 green

- [x] 🟩 **Step 4: P0 — Shared ingestion scaffold**
  - [x] 🟩 `ingestion-pipeline/` package shipped (`436f038`)
  - [x] 🟩 Staging envelope, review queue, shared Supabase/embedding modules
  - [x] 🟩 `data/imports|staging|cache` gitignored; env vars in `.env.example`

- [x] 🟩 **Step 5: P4 — Clinic sales CSV seed**
  - [x] 🟩 `lanes/clinic_csv/parse.py` + `sync/clinic_accounts.py` (insert-only dedupe)
  - [x] 🟩 Live import: **1,662 accounts**, **606 contacts**, **~1,663 embedding chunks**
  - [x] 🟩 Idempotent re-run inserts 0; `match_documents(clinic_account)` verified
  - [ ] 🟥 Check off MASTER_PLAN E2 + catalog A6 after A1 rotation verification

- [x] 🟩 **Step 6: F1 — Vercel deploy prep**
  - [x] 🟩 `next build` passes
  - [x] 🟩 `.vercelignore` excludes Python services + data dirs
  - [ ] 🟥 Import repo to Vercel + set env — *human*
  - [ ] 🟥 Verify login, `/accounts`, `/pipeline`, Ask DocMap against prod Supabase

## Not in this sprint

- P2 clinic Gmail sync (A3) — next after A1 + Vercel
- P1–P3 other ingestion lanes (transcripts, doctor Gmail)
- P5/P6 patient lanes — blocked on privacy review
- Instagram (Phase C), agent crons (E1), carousels — per MASTER_PLAN deferrals
