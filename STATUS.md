# DocMap Intelligence OS Status

Last updated: 2026-07-04 (P4 clinic import live; 4 commits ready on main)

**Master plan:** [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md) | **Deploy:** [`docs/DEPLOY.md`](docs/DEPLOY.md) | **Sprint:** [`docs/EXECUTION_PLAN_2026-07.md`](docs/EXECUTION_PLAN_2026-07.md)

**GitHub:** [jackye426/IntelligenceOS](https://github.com/jackye426/IntelligenceOS)

## Master plan progress

| Phase | Status |
|-------|--------|
| **A** Ops + deploy | **A2–A5 done** — MCP live at `mcp.docmap.co.uk`; data-worker on Railway; **A1 rotation in progress (human)** |
| **B** TikTok M3 | **B1–B7 done** (B8 optional/deferred) |
| **C** Instagram | Not started (fresh-fetch module) |
| **D** Gmail MCP | **Done** — `draft_outreach_email` (draft-only, `confirmed` required) |
| **E** Agents | P0 + **P4 clinic CSV done**; P2 Gmail clinic sync next |
| **F** Vercel | Build + `.vercelignore` ready; **dashboard deploy pending** |

## Prod health (verified 2026-07-04)

| Check | Result |
|-------|--------|
| MCP `GET /health` | **200** `{"status":"ok","service":"docmap-mcp"}` |
| Supabase schema 001–004 | **OK** — all expected tables + `match_documents` RPC |
| `clinic_accounts` | **1,662** rows |
| `document_embeddings` | **~1,848** chunks |
| `content_posts` | **39** |
| `clinic_sales_csv_import` run | **success** — 1,666 seen, 1,262 inserted |
| `match_documents(clinic_account)` | **OK** — semantic search returns Harley St fertility clinics |
| `next build` | **passes** |

## New MCP tools (2026-07-03)

- `find_ab_tests` — filtered A/B hook tests
- `suggest_next_tiktok_angles` — ranked angles from comment analysis
- `draft_outreach_email` — Gmail draft only (`GMAIL_*` env on Railway)

## TikTok pipeline

- **M1 + M2 + M3:** complete
- **Tests:** 13/13 passing (`marketing-pipeline/tests/`)

## Ingestion pipeline (P0 + P4)

- Package: `ingestion-pipeline/` — staging envelope, review queue, hash-skip embeddings
- **P4:** `Clinic sales agent/output/clinic_sales_results.csv` → `clinic_accounts` + contacts + embeddings
- CLI: `python -m ingestion_pipeline sync clinic-csv` or `scripts/ingest-clinic-sales-csv.py`

## Data worker (prod config)

```
SKIP_CONTENT_TRACKER=true
SKIP_HCA=true
```

Cron: daily TikTok sync 03:30 UTC; weekly full refresh + OCR Sun 02:00 UTC.

## Next steps (human)

1. **A1** — Rotate keys (see rotation map below); update Railway (`mcp-server`, `data-worker`) + root `.env.local`; re-verify MCP `/health` + one embed call
2. **Push** — 4 local commits on `main` (ingestion-pipeline, P4, hygiene, docs) — triggers Railway redeploy
3. **F1** — Import repo to Vercel; set `SUPABASE_*`, `OPENROUTER_API_KEY`, `SESSION_PASSWORD`
4. **P2** — Clinic Gmail sync into Supabase (after CSV seed stable)
5. **UI** — 1,662 clinics in "Identified" may be noisy; consider default filter/stage if needed
