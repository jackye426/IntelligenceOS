# Instagram marketing pipeline (placeholder)

Instagram ingestion remains in `data-worker/jobs/content_tracker.py` (Instagram-only CSV rows).

## Future module

When implemented, this package will mirror the TikTok layout:

```
instagram/
  orchestrator.py
  stages/
  sync/supabase.py
```

Same Supabase target: `content_posts` with `platform=instagram`.

Data source: `Social media analysis/Marketing - Content - Tracker - Content Tracker (3).csv`
