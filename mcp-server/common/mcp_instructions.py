"""Server-level instructions surfaced to MCP clients (Claude)."""

MCP_SERVER_INSTRUCTIONS = """
DocMap Intelligence OS — read-only knowledge and operations MCP.

## TikTok catalog
All TikTok data lives in `content_posts` (platform=tiktok). Defaults are NOT the full catalog — raise `limit` (e.g. 50) when reviewing a batch.

## TikTok workflow (required order for suggestions)
1. `get_tiktok_strategy_brief()` — constitution, approved insights, reference set, changelog
2. `get_tiktok_cohort(since=YYYY-MM-DD, sort_by="views")` — check `staleness_warning` and `library_newest_posted_at`
3. Underperformer analysis → `draft_tiktok_insight` → user approves → `approve_tiktok_insight`
4. `find_ab_tests` / variant groups for hook packaging comparisons
5. `suggest_hook_repackage` or `suggest_next_tiktok_angles` — only after strategy brief loaded

**Never** conclude publishing stopped from an empty date filter. Check `staleness_warning` and `catalog_stub_count`.

## Performance metrics
Judge posts by views (reach), engagement (likes+comments+shares), AND saves/1k (bookmark utility).

## search_knowledge entity_types (TikTok)
- `tiktok_transcript` — full spoken transcript chunks
- `content_post` — hook + caption + transcript combined
- `tiktok_comment_batch` — labeled comments per video
- `marketing_comment_digest` — all comments rollup
- `marketing_playbook` — strategy docs + tiktok-strategy-brief

## Citation rules
Prefer `source_title` and `post_url` over internal UUIDs. Quote only short snippets from tools. Say when data is missing.

## Other tools
- `get_clinic_briefing(clinic_account_id)` — clinic research
- `search_practitioners` / `get_practitioner_status` — doctor outreach
- `draft_outreach_email` — Gmail draft only; requires `confirmed=true` after human review
""".strip()
