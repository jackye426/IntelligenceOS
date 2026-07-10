# Marketing Pipeline

TikTok-first marketing intelligence package for DocMap Intelligence OS.

## Setup

```bash
cd marketing-pipeline
pip install -e .
# Optional for full refresh (yt-dlp, Whisper):
pip install -e ".[media]"
```

Env vars (from repo root `.env.local`):

| Var | Purpose |
|-----|---------|
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | Sync to Intelligence OS |
| `OPENROUTER_API_KEY` | Embeddings, OCR vision, component extract |
| `MODEL_OCR` | Vision OCR (default `google/gemini-3-flash-preview`) |
| `MODEL_COMPONENTS` | Text LLM for video component cards (default `deepseek/deepseek-v4-flash`; try `deepseek/deepseek-v4-pro` if needed) |

## CLI

```bash
python -m marketing_pipeline tiktok export      # build dataset + master txt from local data
python -m marketing_pipeline tiktok analyze     # hooks, A/B pairs, dataset, evidence draft
python -m marketing_pipeline tiktok refresh --since 2026-04-20  # catalog + OCR + comments + export
python -m marketing_pipeline tiktok refresh-comments            # fetch/label/compile comments
python -m marketing_pipeline tiktok ocr-hooks [--no-download]   # on-screen hook OCR only (MODEL_OCR)
python -m marketing_pipeline tiktok extract-components [--video-id ID] [--force] [--limit N]
# ↑ batch component cards: hook type/attrs, TOFU|MOFU|BOFU, CTA, topic, speaker (MODEL_COMPONENTS)
python -m marketing_pipeline tiktok sync-supabase [--dry-run] [--skip-embed]
python -m marketing_pipeline tiktok sync-playbooks              # embed playbooks + ALL_COMMENTS
python -m marketing_pipeline tiktok import-playbooks            # copy strategy docs into playbooks/
python -m marketing_pipeline tiktok display-snapshots           # Display API velocity layer
python -m marketing_pipeline tiktok studio-listen [--recent N]  # Studio insight capture
python -m marketing_pipeline tiktok ingest-studio-insight PATH
python -m marketing_pipeline tiktok ingest-bc-csv [DIR]         # Business Center CSVs
```

**OCR:** ffmpeg on PATH (or `FFMPEG_PATH`), `OPENROUTER_API_KEY`, `MODEL_OCR`. Install media extras: `pip install -e ".[media]"`.

**Components:** run after transcripts/hooks exist. Writes `tiktok/data/analysis/video_components/{id}.json` and index; `sync-supabase` attaches `metadata.components`. MCP reads via `get_video_components` / `analyze_components` (no live extract). Plan: [`docs/EXECUTION_PLAN_VIDEO_COMPONENTS.md`](../docs/EXECUTION_PLAN_VIDEO_COMPONENTS.md).

## Data layout

Canonical artifacts live under `marketing-pipeline/tiktok/data/`:

- `transcripts/` — per-video JSON + `ALL_COMPLETE_TRANSCRIPTS.txt`
- `catalog/` — docmap catalog JSON
- `comments_raw/` — raw comment fetches
- `analysis/` — labeled comments, strategy brief/state, **video_components/**
- `playbooks/` — strategy docs + `component-vocabulary.md` (working labels)
- `media/` — downloaded mp4 (gitignored)
- `ocr/` — frame cache + OCR JSON (gitignored)
- `exports/tiktok_marketing_dataset.json` — sync input

Legacy `Social media analysis/tiktok_analysis/` is used only by `refresh` until fully ported.

## Related MCP / docs

- Team onboarding: [`docs/MCP_ONBOARDING.md`](../docs/MCP_ONBOARDING.md)
- Prompt ritual: [`docs/mcp_prompt_guide.md`](../docs/mcp_prompt_guide.md)
- Decision log + strategy: [`docs/EXECUTION_PLAN_TIKTOK_STRATEGY_AND_SYNC.md`](../docs/EXECUTION_PLAN_TIKTOK_STRATEGY_AND_SYNC.md)

## Milestone status

| Area | Status |
|------|--------|
| OCR / hooks / comments / playbooks sync | Live |
| Strategy brief + insight draft/approve | Live (MCP) |
| Decision log (commit → outcome) | Live (MCP) |
| Video component extract (batch) | **v1** — explicit CLI; not on daily cron |
| Display / Studio metric layers | In progress (`sql/005_tiktok_metrics.sql`) |

Instagram module: see `src/marketing_pipeline/instagram/README.md`.
