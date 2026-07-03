# DocMap Intelligence OS Status

Last updated: 2026-07-03 (master plan execution — phase 1)

**Master plan:** [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md) | **Deploy:** [`docs/DEPLOY.md`](docs/DEPLOY.md)

**GitHub:** [jackye426/IntelligenceOS](https://github.com/jackye426/IntelligenceOS)

## Master plan progress

| Phase | Status |
|-------|--------|
| **A** Ops + deploy | A5 done; A3/A4 need Railway setup (see DEPLOY.md); A1/A2 human |
| **B** TikTok M3 | B1 partial, B5–B7 done; B2–B4 legacy transcribe/compile remain |
| **C** Instagram | Not started (fresh-fetch module) |
| **D** Gmail MCP | **Done** — `draft_outreach_email` (draft-only, `confirmed` required) |
| **E** Agents | Not started |
| **F** Vercel | `vercel.json` ready; deploy pending |

## New MCP tools (2026-07-03)

- `find_ab_tests` — filtered A/B hook tests
- `suggest_next_tiktok_angles` — ranked angles from comment analysis
- `draft_outreach_email` — Gmail draft only (`GMAIL_*` env on Railway)

## TikTok pipeline

- **M1 + M2:** complete (33/39 on-screen hooks)
- **M3 partial:** `fetch_catalog` in package; legacy `--skip-catalog`; weekly OCR cron
- **Tests:** 8/8 passing

## Data worker (prod config)

Set on Railway:
```
SKIP_CONTENT_TRACKER=true
SKIP_HCA=true
```

Cron: daily TikTok sync 03:30 UTC; weekly full refresh + OCR Sun 02:00 UTC.

## Next steps (human)

1. **A1** — Rotate credentials if any were exposed
2. **A3/A4** — Deploy MCP + data-worker per `docs/DEPLOY.md`
3. **F1** — Deploy Next.js to Vercel
4. Set `GMAIL_*` on MCP Railway service for draft tool
