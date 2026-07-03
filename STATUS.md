# DocMap Intelligence OS Status

Last updated: 2026-07-03 (milestone 2 complete)

## What This Project Is

DocMap Intelligence OS is an internal data and agent workspace for clinic/practitioner outreach, marketing intelligence, and operational search. The main app is a Next.js + Supabase product with account, research, pipeline, outreach, and chat/ask surfaces. Around it are specialist agent/data areas for doctors, clinics, TikTok/social analysis, carousel generation, appointment monitoring, and MCP access.

The MCP server is the interaction layer over the data: it lets assistants query, search, summarize, and reason over Supabase-backed knowledge. Scheduled or routine data collection lives in workers/pipelines; MCP exposes the resulting data and insights.

## What We Have

- `app/`, `lib/`, `worker/`: the core Next.js app, API routes, OpenRouter helpers, Supabase helpers, and background jobs.
- `sql/`: Supabase schema migrations for clinic intelligence, embeddings, doctor outreach, and MCP source metadata.
- `mcp-server/`: MCP tools for knowledge search, practitioner search/status, content performance, patient demand patterns, appointment availability, weekly briefing, **TikTok marketing insights**, and **TikTok content briefing**.
- `data-worker/`: scheduled ingestion for Instagram content tracker, TikTok marketing pipeline (via package), and HCA appointment data.
- `marketing-pipeline/`: TikTok-first marketing intelligence package (CLI, stages, dataset export, Supabase sync).
- `Doctors Sales Agent/`: practitioner/outreach tooling, including upload scripts for the `integrated_practitioner_with_phin` dataset.
- `Social media analysis/tiktok_analysis/`: legacy TikTok scripts (refresh only; canonical data under `marketing-pipeline/tiktok/data/`).
- `Carousel agents V2/`: carousel ideation/generation tooling plus Instagram slide dataset and OCR-oriented utilities.

**GitHub:** [jackye426/IntelligenceOS](https://github.com/jackye426/IntelligenceOS) (`main` branch)

## TikTok Marketing Pipeline

### Milestone 1 (shipped)
- Package CLI: `export`, `analyze`, `refresh`, `sync-supabase`
- 39 videos → `tiktok_marketing_dataset.json` → Supabase `content_posts` + embeddings
- MCP: `get_tiktok_marketing_insights`

### Milestone 2 (complete — 2026-07-03)
- **OCR:** vision LLM (`google/gemini-3-flash-preview`) on ffmpeg frames → **33/39 on-screen hooks** (85%)
- **Comments:** `refresh-comments` → 48 videos, 505 comments → `ALL_COMMENTS.txt` + `marketing_comment_digest` embeddings
- **Playbooks:** `import-playbooks` + `sync-playbooks` → `marketing_playbook` embeddings
- **Legacy unify:** `compile_complete_transcripts.py` reads `comments_raw/` by default (`--live-comments` for API)
- **MCP:** `get_tiktok_content_briefing` (performance + strategy + audience search)
- **Cron:** `refresh-comments` → `export` → `sync-supabase` → `sync-playbooks`

### CLI reference

```bash
python -m marketing_pipeline tiktok export
python -m marketing_pipeline tiktok refresh-comments
python -m marketing_pipeline tiktok ocr-hooks [--force]
python -m marketing_pipeline tiktok sync-supabase
python -m marketing_pipeline tiktok sync-playbooks
python -m marketing_pipeline tiktok import-playbooks
python -m marketing_pipeline tiktok refresh --since 2026-04-20
```

## Test Results (2026-07-03)

| Test | Result |
|------|--------|
| `pytest marketing-pipeline/tests/` | **6/6 passed** |
| `ocr-hooks --force` | 39 processed, **33 with_hook**, 0 errors |
| `export` | 39 videos, 4 A/B pairs, 33 onscreen_hooks |
| `sync-supabase` | 39 rows updated, 34 embeddings written |
| MCP `/health` | `{"status":"ok","service":"docmap-mcp"}` |

**Live Supabase:** 39 TikTok `content_posts`; embeddings across `content_post`, `tiktok_transcript`, `tiktok_comment_batch`, `marketing_playbook`, `marketing_comment_digest`.

## Current Marketing Data Loop

```
refresh-comments → export → sync-supabase → sync-playbooks → MCP
(weekly) refresh + ocr-hooks for new videos
```

Canonical on-disk sources:
- `marketing-pipeline/tiktok/data/transcripts/ALL_COMPLETE_TRANSCRIPTS.txt`
- `marketing-pipeline/tiktok/data/exports/ALL_COMMENTS.txt`
- `marketing-pipeline/tiktok/data/playbooks/`
- `marketing-pipeline/tiktok/data/exports/tiktok_marketing_dataset.json`

## To Do (milestone 3+)

### TikTok
1. Port full `refresh` stages into the package (reduce legacy script dependence).
2. Add MCP tools: `find_ab_tests`, `suggest_next_tiktok_angles`.
3. Optional `sql/005_tiktok_marketing.sql` if JSONB metadata becomes limiting.

### Instagram / carousels
4. Build `marketing-pipeline/instagram/` module.
5. Re-run `scripts/ingest-content-tracker.py` if Instagram rows needed in `content_posts`.

### Platform / ops
6. Deploy `mcp-server` and `data-worker` to Railway (or equivalent).
7. Add `draft_outreach_email` MCP tool (Gmail integration).
