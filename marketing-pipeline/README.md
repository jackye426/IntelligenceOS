# Marketing Pipeline

TikTok-first marketing intelligence package for DocMap Intelligence OS.

## Setup

```bash
cd marketing-pipeline
pip install -e .
# Optional for full refresh (yt-dlp, Whisper):
pip install -e ".[media]"
```

Env vars (from repo root `.env.local`): `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `OPENROUTER_API_KEY`.

## CLI

```bash
python -m marketing_pipeline tiktok export      # build dataset + master txt from local data
python -m marketing_pipeline tiktok analyze     # hooks, A/B pairs, dataset, evidence draft
python -m marketing_pipeline tiktok refresh --since 2026-04-20  # legacy + OCR + comments + export
python -m marketing_pipeline tiktok refresh-comments            # fetch/label/compile comments
python -m marketing_pipeline tiktok ocr-hooks [--no-download]   # on-screen hook OCR only
python -m marketing_pipeline tiktok sync-supabase [--dry-run] [--skip-embed]
python -m marketing_pipeline tiktok sync-playbooks              # embed playbooks + ALL_COMMENTS
python -m marketing_pipeline tiktok import-playbooks              # copy Downloads strategy docs
```

**OCR requirements:** ffmpeg on PATH (or `FFMPEG_PATH`), `OPENROUTER_API_KEY`, optional `MODEL_OCR` (default `google/gemini-2.0-flash-001`). Install media tools: `pip install -e ".[media]"`.

## Data layout

Canonical artifacts live under `marketing-pipeline/tiktok/data/`:

- `transcripts/` — per-video JSON + `ALL_COMPLETE_TRANSCRIPTS.txt`
- `catalog/` — docmap catalog JSON
- `comments_raw/` — raw comment fetches
- `analysis/` — labeled comments + summaries
- `playbooks/` — strategy docs + evidence (approved only embedded)
- `media/` — downloaded mp4 (gitignored)
- `ocr/` — frame cache + OCR JSON (gitignored)
- `exports/tiktok_marketing_dataset.json` — sync input

Legacy `Social media analysis/tiktok_analysis/` is used only by `refresh` until fully ported.

Instagram module: see `src/marketing_pipeline/instagram/README.md`.
