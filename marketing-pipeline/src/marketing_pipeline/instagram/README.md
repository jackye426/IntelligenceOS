# Instagram marketing pipeline

Instagram ingestion mirrors the TikTok pipeline but is format-first:
Reels, carousels, and static posts are normalized into
`content_posts(platform=instagram)`.

## Sources

- Fresh public source: Instaloader for `@docmapuk`
- Optional Reel media source: yt-dlp for transcription/component work
- Historical/enrichment source: `Social media analysis/Marketing - Content - Tracker - Content Tracker (3).csv`

## CLI

```bash
python -m marketing_pipeline instagram fetch --account docmapuk --limit 50
python -m marketing_pipeline instagram export
python -m marketing_pipeline instagram sync-supabase --dry-run
```

Install the optional fetch dependency with:

```bash
pip install -e ".[instagram]"
```

## Output

- Raw fetches: `instagram/data/raw/`
- Dataset: `instagram/data/exports/instagram_marketing_dataset.json`
- Strategy brief: `instagram/data/analysis/instagram_strategy_brief.json`
- Supabase target: `content_posts` with `platform=instagram`
