# DocMap Intelligence OS Status

Last updated: 2026-07-04 (A2–A4 verified live; close-out sprint started — see [`docs/EXECUTION_PLAN_2026-07.md`](docs/EXECUTION_PLAN_2026-07.md))

**Master plan:** [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md) | **Deploy:** [`docs/DEPLOY.md`](docs/DEPLOY.md)

**GitHub:** [jackye426/IntelligenceOS](https://github.com/jackye426/IntelligenceOS)

## Master plan progress

| Phase | Status |
|-------|--------|
| **A** Ops + deploy | **A2–A5 done** — MCP live at `mcp.docmap.co.uk`; data-worker on Railway logging `data_ingestion_runs`; **A1 rotation pending (human)** |
| **B** TikTok M3 | **B1–B7 done** (B8 optional/deferred) |
| **C** Instagram | Not started (fresh-fetch module) |
| **D** Gmail MCP | **Done** — `draft_outreach_email` (draft-only, `confirmed` required) |
| **E** Agents | **E2 done** — `ingestion-pipeline/` package + clinic CSV seed: 1,662 accounts, 606 draft contacts, embeddings live; E1 WhatsApp cron pending |
| **F** Vercel | Build verified + `.vercelignore` added; dashboard import + env vars pending (human) |

## New MCP tools (2026-07-03)

- `find_ab_tests` — filtered A/B hook tests
- `suggest_next_tiktok_angles` — ranked angles from comment analysis
- `draft_outreach_email` — Gmail draft only (`GMAIL_*` env on Railway)

## TikTok pipeline

- **M1 + M2:** complete (33/39 on-screen hooks)
- **M3:** complete — package-native refresh (catalog, stats, transcribe, master compile); weekly OCR cron
- **Tests:** 11/11 passing

## Data worker (prod config)

Set on Railway:
```
SKIP_CONTENT_TRACKER=true
SKIP_HCA=true
```

Cron: daily TikTok sync 03:30 UTC; weekly full refresh + OCR Sun 02:00 UTC.

## Next steps (human)

1. **A1** — Rotate credentials (Supabase, OpenRouter, Google) and update Railway/Vercel + `.env.local`
2. **F1** — Import repo to Vercel + set env vars (build prep done in close-out sprint)
3. Set `GMAIL_*` on MCP Railway service for draft tool
