# Instagram marketing pipeline

Instagram ingestion mirrors the TikTok pipeline but is format-first:
Reels, carousels, and static posts are normalized into
`content_posts(platform=instagram)`.

## Sources

- Fresh public source: Instaloader for `@docmapuk` (**requires login session**)
- Optional Reel media source: yt-dlp for transcription/component work
- Historical/enrichment source: `Social media analysis/Marketing - Content - Tracker - Content Tracker (3).csv`

## One-time login (required)

Instagram blocks anonymous scrape. Create a session as `@docmapuk`:

```bash
cd marketing-pipeline
pip install -e ".[instagram]"
python -m marketing_pipeline instagram login --account docmapuk
```

Type the password (and 2FA if prompted). This writes:

`marketing-pipeline/instagram/data/session-docmapuk`

**Do not commit this file.** Copy it onto the Railway data-worker volume:

`/app/marketing-data/instagram/session-docmapuk`

(Same path the daily 03:10 cron checks.)

## CLI

```bash
python -m marketing_pipeline instagram login --account docmapuk
python -m marketing_pipeline instagram fetch --account docmapuk --limit 50
python -m marketing_pipeline instagram export
python -m marketing_pipeline instagram sync-supabase --dry-run
```

Install the optional fetch dependency with:

```bash
pip install -e ".[instagram]"
```

## Output

- Session: `instagram/data/session-docmapuk` (gitignored)
- Raw fetches: `instagram/data/raw/`
- Dataset: `instagram/data/exports/instagram_marketing_dataset.json`
- Strategy brief: `instagram/data/analysis/instagram_strategy_brief.json`
- Supabase target: `content_posts` with `platform=instagram`
