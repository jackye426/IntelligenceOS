# DocMap Intelligence OS Status

Last updated: 2026-06-28 (milestone 2 verified)

## What This Project Is

DocMap Intelligence OS is an internal data and agent workspace for clinic/practitioner outreach, marketing intelligence, and operational search. The main app is a Next.js + Supabase product with account, research, pipeline, outreach, and chat/ask surfaces. Around it are specialist agent/data areas for doctors, clinics, TikTok/social analysis, carousel generation, appointment monitoring, and MCP access.

The MCP server is the interaction layer over the data: it lets assistants query, search, summarize, and reason over Supabase-backed knowledge. Scheduled or routine data collection lives in workers/pipelines; MCP exposes the resulting data and insights.

## What We Have

- `app/`, `lib/`, `worker/`: the core Next.js app, API routes, OpenRouter helpers, Supabase helpers, and background jobs.
- `sql/`: Supabase schema migrations for clinic intelligence, embeddings, doctor outreach, and MCP source metadata.
- `mcp-server/`: MCP tools for knowledge search, practitioner search/status, content performance, patient demand patterns, appointment availability, weekly briefing, **TikTok marketing insights**, and **TikTok content briefing** (playbooks + comment digest search).
- `data-worker/`: scheduled ingestion for Instagram content tracker, TikTok marketing pipeline (via package), and HCA appointment data.
- `marketing-pipeline/`: **new** TikTok-first marketing intelligence package (CLI, stages, dataset export, Supabase sync).
- `Doctors Sales Agent/`: practitioner/outreach tooling, including upload scripts for the `integrated_practitioner_with_phin` dataset.
- `Social media analysis/tiktok_analysis/`: legacy TikTok scripts and artifacts (still used by `refresh`; canonical data now under `marketing-pipeline/tiktok/data/`).
- `Carousel agents V2/`: carousel ideation/generation tooling plus Instagram slide dataset and OCR-oriented utilities.

## What We Recently Did

### Practitioner data (prior)
- Confirmed the practitioner table name is `integrated_practitioner_with_phin`.
- Uploaded `40,876` practitioner rows into Supabase project `okpbevwdqgzmnrowifcn`.
- Verified the live Supabase table contains `40,876` rows.

### TikTok marketing pipeline (milestone 1 — shipped)
- Created installable package at `marketing-pipeline/` with CLI:
  - `python -m marketing_pipeline tiktok export`
  - `python -m marketing_pipeline tiktok analyze`
  - `python -m marketing_pipeline tiktok refresh --since YYYY-MM-DD`
  - `python -m marketing_pipeline tiktok sync-supabase [--dry-run] [--skip-embed]`
- Migrated TikTok artifacts to `marketing-pipeline/tiktok/data/` (transcripts, catalog, comments_raw, analysis).
- Canonical structured export: `marketing-pipeline/tiktok/data/exports/tiktok_marketing_dataset.json`.
- Implemented pipeline stages: parse master transcripts, load catalog, comment analysis, hook extraction, A/B pair detection, on-screen hook OCR stub, legacy refresh adapter.
- Supabase sync (`tiktok_marketing_sync`):
  - Upserts `content_posts` (`platform=tiktok`) with canonical metrics + derived rates (`saves_per_1k_views`, etc.)
  - Writes rich `metadata` (hook_detail, comment_analysis, ab_pairs, `source: marketing_pipeline`)
  - Embeddings: `content_post`, `tiktok_transcript`, `tiktok_comment_batch` (themes array fix)
  - Prunes stale TikTok posts; orphan embedding cleanup; content-hash skip for unchanged chunks
- Wired `data-worker/main.py` cron (03:30 UTC) to run export + sync via the package.
- Updated `scripts/ingest-tiktok.py` as a thin wrapper.
- Added MCP tool `get_tiktok_marketing_insights` (top posts by saves/1k views, hook variants, A/B tests, suggested angles).
- Instagram placeholder: `marketing-pipeline/src/marketing_pipeline/instagram/README.md` (Instagram ingest remains `data-worker/jobs/content_tracker.py`).

### TikTok marketing pipeline (milestone 2 — shipped)
- **OCR pipeline** (vision LLM via OpenRouter, not pytesseract): `download_media` → `extract_frames` (0/0.5/1/2s) → `extract_onscreen_hook` with per-video JSON cache under `tiktok/data/ocr/`.
- **Comments refresh path**: catalog-driven `collect_comments` (7-day TTL) → `rebuild_comment_analysis` → `write_comments_digest` → `exports/ALL_COMMENTS.txt` (48 videos, 505 comments after first run).
- **Playbooks lane**: `import-playbooks` copies strategy docs from Downloads; `draft_evidence_playbook` auto-drafts evidence; `sync-playbooks` embeds `marketing_playbook` + `marketing_comment_digest`.
- New CLI commands:
  - `python -m marketing_pipeline tiktok import-playbooks`
  - `python -m marketing_pipeline tiktok refresh-comments`
  - `python -m marketing_pipeline tiktok ocr-hooks [--limit N]`
  - `python -m marketing_pipeline tiktok sync-playbooks`
- `data-worker` daily cron: `refresh-comments` → `export` → `sync-supabase` → `sync-playbooks`.
- MCP: `get_tiktok_content_briefing` (composite insights + playbook/digest semantic search); `get_tiktok_marketing_insights` now exposes `hook_source` and `missing_onscreen_hook`.
- Playbooks on disk: `content-instruction.md`, `viral-format.md`, `evidence/recipe-2026-06.md`.

## Test Results (2026-06-28)

| Test | Result |
|------|--------|
| `pytest marketing-pipeline/tests/` | **5/5 passed** (milestone 1 + milestone 2) |
| `tiktok import-playbooks` | 3 playbooks imported from Downloads |
| `tiktok refresh-comments` | 47 fetched, 48 videos in digest, 505 comments |
| `tiktok export` | **39 videos**, **4 A/B pairs**; evidence draft written |
| `tiktok sync-supabase` | 39 rows updated, **14** new/changed embeddings |
| `tiktok sync-playbooks` | **3** playbook chunks + **59** comment-digest chunks embedded |
| MCP `main.py` import | `get_tiktok_content_briefing_tool` registered |

**Live Supabase snapshot:** 39 `content_posts` (all TikTok), marketing embeddings across `content_post`, `tiktok_transcript`, `tiktok_comment_batch`, `marketing_playbook`, and `marketing_comment_digest` lanes.

**OCR status:** `onscreen_hooks: 0` — pipeline code is ready but no local `.mp4` files exist and `yt-dlp` is not on PATH. Install `yt-dlp`, then run `ocr-hooks` (requires `ffmpeg` ✓, `OPENROUTER_API_KEY`).

## Current Marketing Data Picture

TikTok marketing is now productized as a repeatable loop:

```
refresh-comments → export → sync-supabase → sync-playbooks → MCP
(weekly) refresh + ocr-hooks for new videos
```

Canonical on-disk sources:
- Master transcripts: `marketing-pipeline/tiktok/data/transcripts/ALL_COMPLETE_TRANSCRIPTS.txt`
- Comment digest: `marketing-pipeline/tiktok/data/exports/ALL_COMMENTS.txt`
- Playbooks: `marketing-pipeline/tiktok/data/playbooks/`
- Sync input: `marketing-pipeline/tiktok/data/exports/tiktok_marketing_dataset.json`

MCP tools: `get_tiktok_marketing_insights` (performance + hooks + A/B) and `get_tiktok_content_briefing` (strategy docs + comment themes). Restart the MCP server after pulling latest code.

**Note:** Re-run `python scripts/ingest-content-tracker.py` if Instagram rows are needed in `content_posts` — TikTok sync only touches `platform=tiktok`.

## To Do

### TikTok — next
1. **Run OCR**: install `yt-dlp`, download media, run `ocr-hooks` to populate `onscreen_hook` (target ~80% coverage on talking-head videos).
2. Unify `compile_complete_transcripts.py` to read `comments_raw/` instead of live API fetch.
3. Port full `refresh` stages into the package (reduce legacy `tiktok_analysis/scripts/` dependence).
4. Add dedicated MCP tools: `find_ab_tests`, `suggest_next_tiktok_angles`.
5. Optional Phase 2 SQL (`sql/005_tiktok_marketing.sql`): `tiktok_hooks`, `tiktok_ab_pairs` if JSONB metadata becomes limiting.

### Instagram / carousels
6. Build `marketing-pipeline/instagram/` module mirroring TikTok pattern.
7. Extend carousel analysis into the same pipeline model.

### Platform / ops
8. Deploy `mcp-server` and `data-worker` to Railway (or equivalent).
9. Add `draft_outreach_email` MCP tool (Gmail integration — deferred from MCP plan).
10. Re-run Instagram content tracker ingest to normalize metrics and restore Instagram rows if missing.
