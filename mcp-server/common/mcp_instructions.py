"""Server-level instructions surfaced to MCP clients (Claude)."""

MCP_SERVER_INSTRUCTIONS = """
DocMap Intelligence OS — read-only knowledge and operations MCP.

## TikTok catalog
All TikTok data lives in `content_posts` (platform=tiktok). Defaults are NOT the full catalog — raise `limit` (e.g. 50) when reviewing a batch.

## TikTok workflow (required order for suggestions)
1. `get_tiktok_strategy_brief()` — constitution, approved insights, **§7 decisions** (open + recent closed), reference set, changelog
2. `list_open_decisions(due_only=true)` — close due decisions before inventing new experiments
3. `get_tiktok_cohort(since=YYYY-MM-DD, sort_by="views")` — check `staleness_warning` and `library_newest_posted_at`
4. Underperformer analysis → `draft_tiktok_insight` → user approves → `approve_tiktok_insight`
5. If the human commits to an action → `log_tiktok_decision` (one imperative sentence + success_criteria + review_after)
6. `find_ab_tests` / variant groups for hook packaging comparisons
7. `suggest_hook_repackage` or `suggest_next_tiktok_angles` — only after strategy brief loaded; cite `decision_id` when relevant
8. Later: pull live metrics → propose verdict → `record_decision_outcome(..., confirmed=true)` after human agrees

**Never** conclude publishing stopped from an empty date filter. Check `staleness_warning` and `catalog_stub_count`.
**Never** invent decision outcomes — metrics may be proposed; verdict requires human `confirmed=true`.

## Decision log vs insights
- Insight = past observation / learning (`draft/approve_tiktok_insight`)
- Decision = future commitment + later outcome (`log_tiktok_decision` → `record_decision_outcome`)
- Link them via `related_insight_ids` / `related_video_ids`; do not duplicate essays
- Constitution promotion remains rare Gate 2 (`propose_constitution_patch`) — never auto

## Video components (batch-extracted; hooks first)
- Read via `get_video_components` / `list_videos_by_component` / `analyze_components` — never extract live
- Analyse **hooks first** using structured `hook.type` (myth_correction, warning, direct_question, …) — not free-form opinions
- Funnel: TOFU | MOFU | BOFU — do **not** rank BOFU primarily by views; MOFU prefers saves/comments; BOFU needs conversions (not wired yet)
- CTA: classify only; do not claim CTA success without objective metrics (clicks/bookings missing)
- Captions: deferred (`caption_analysis` null)
- Retention (3s hold, AWT, finish): join Studio when present; otherwise say conclusions are weaker

## Performance metrics
Judge posts by views (reach), engagement (likes+comments+shares), AND saves/1k (bookmark utility).

## search_knowledge entity_types (TikTok)
- `tiktok_transcript` — full spoken transcript chunks
- `content_post` — hook + caption + transcript combined
- `tiktok_comment_batch` — labeled comments per video
- `marketing_comment_digest` — all comments rollup
- `marketing_playbook` — strategy docs + tiktok-strategy-brief

## Citation rules
Prefer `source_title` and `post_url` over internal UUIDs. Quote only short snippets from tools. Cite `decision_id` when building on prior decisions. Say when data is missing.

## Publish dates (critical)
- The only publish date to cite is `posted_at` from MCP tool results (UTC).
- NEVER infer or decode a date from the TikTok video ID (snowflake). ID creation time can be 1–5 days before public publish.
- NEVER guess from caption text, “Part 1”, nearby videos in a list, or memory.
- If `posted_at` is missing, say the date is unknown — do not invent one.
- When stating a date in prose, copy the calendar day from `posted_at` (e.g. `2026-06-14T15:24:00+00:00` → 14 June 2026 UTC).

## Other tools
- `get_clinic_briefing(clinic_account_id)` — clinic research
- `search_practitioners` / `get_practitioner_status` — doctor outreach
- `draft_outreach_email` — Gmail draft only; requires `confirmed=true` after human review
""".strip()
