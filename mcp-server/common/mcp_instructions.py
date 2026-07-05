"""Server-level instructions surfaced to MCP clients (Claude)."""

MCP_SERVER_INSTRUCTIONS = """
DocMap Intelligence OS — read-only knowledge and operations MCP.

## TikTok catalog (~40 videos)
All TikTok data lives in `content_posts` (platform=tiktok). Defaults are NOT the full catalog — raise `limit` (e.g. 50) when reviewing a batch.

## TikTok weekly review workflow
1. `get_tiktok_cohort(since=YYYY-MM-DD, sort_by="views")` — recent posts with outperform/underperform tiers
2. `get_tiktok_marketing_insights(limit=15)` — multi-metric rankings (views, engagement, saves/1k)
3. `find_ab_tests(since=...)` — hook A/B pairs (same content, different hook packaging)
4. `get_tiktok_video(video_id)` — full caption, transcript, hooks, comment analysis for one video
5. `suggest_hook_repackage(video_id)` — compare underperformer to winning hooks; propose swaps
6. `record_ab_learning(...)` — persist human-approved learning after review
7. `get_ab_learnings()` — retrieve approved learnings next session

## Performance metrics
Judge posts by views (reach), engagement (likes+comments+shares), AND saves/1k (bookmark utility). Use `sort_by` on cohort/insights tools — do not rely on saves/1k alone.

## search_knowledge entity_types (TikTok)
- `tiktok_transcript` — full spoken transcript chunks
- `content_post` — hook + caption + transcript combined
- `tiktok_comment_batch` — labeled comments per video
- `marketing_comment_digest` — all comments rollup
- `marketing_playbook` — strategy + approved evidence learnings

## Citation rules
Prefer `source_title` and `post_url` over internal UUIDs. Quote only short snippets from tools. Say when data is missing.

## Other tools
- `get_clinic_briefing(clinic_account_id)` — clinic research
- `search_practitioners` / `get_practitioner_status` — doctor outreach
- `draft_outreach_email` — Gmail draft only; requires `confirmed=true` after human review
""".strip()
