# DocMap MCP Prompt Guide

Use these prompts with Claude Desktop after connecting to the DocMap MCP server. Always ask for citations when making claims about clinics, practitioners, content, or patient demand.

## Practitioner search

- "Search practitioners named `[name]` and summarize specialty and location."
- "Find gynaecology practitioners in London with outreach history."
- "Who have we contacted recently among BSGE-related practitioners?"

Pair with:

- `search_practitioners`
- `get_practitioner_status`

## Clinic briefing

- "Give me a briefing for clinic account `[uuid]` including approved observations and contacts."
- "What do we know about `[clinic name]` from approved research observations?"

Pair with:

- `get_clinic_briefing`

## Patient demand patterns

- "What patient demand themes show up most often in recent conversation metadata?"
- "Summarize top condition tags and needs from patient conversations — metadata only."

Pair with:

- `get_patient_demand_patterns`

Note: this tool uses tagged metadata only, not raw chat transcripts.

## Content performance

- "What Instagram content performed best on endometriosis topics?"
- "Show top TikTok posts by saves per 1k views and summarize hooks that worked."
- "Which recent posts had the strongest engagement?"

Pair with:

- `get_content_performance`
- `get_tiktok_marketing_insights`
- `search_knowledge` with `entity_type: content_post`

## TikTok marketing briefing

- "Give me a TikTok content briefing: what's working, what patients ask in comments, and what our playbook says to post next."
- "What hook patterns are winning on TikTok and what should we film next for pre-surgery patients?"

### Strategy-first ritual (required before suggestions)

1. `get_tiktok_strategy_brief()` — constitution, approved insights, **§7 decisions**, reference set, changelog
2. `list_open_decisions(due_only=true)` — close due decisions before new experiments
3. `get_tiktok_cohort(since=YYYY-MM-DD, sort_by="views", limit=50)` — check `staleness_warning` if empty
4. Underperformer: `get_tiktok_video(video_id)` → discuss in chat → `draft_tiktok_insight` → user approves → `approve_tiktok_insight`
5. If the human commits to an action → `log_tiktok_decision(decision, success_criteria=..., review_after=YYYY-MM-DD, related_video_ids=[...])`
6. `find_ab_tests` / `find_variant_groups(since=YYYY-MM-DD, winner_by="views")` — variant groups (2–N videos)
7. `suggest_hook_repackage(video_id)` — loads strategy brief + open decisions; human approves before filming
8. Later session: metrics → propose verdict → `record_decision_outcome(decision_id, verdict, confirmed=true)`
9. Gate 2 (rare): `propose_constitution_patch(insight_id, proposed_bullet)` — returns markdown to paste into `content-instruction.md`

**Never** conclude publishing stopped from an empty `since` filter — read `staleness_warning` and `catalog_stub_count`.
**Never** invent decision outcomes — require human `confirmed=true`.
**Never** infer publish dates from TikTok video IDs — cite only `posted_at` from tools (UTC).

### Decision log (commitments + outcomes)

Insight = past learning. Decision = what we will do next + later verdict.

Good decision text:
> “Repost surgical-photos clip with imperative CTA hook. Success = saves/1k ≥ top-quartile of last 30 days within 7 days.”

Pair with:

- `log_tiktok_decision` / `list_open_decisions` / `get_tiktok_decision`
- `record_decision_outcome` (requires `confirmed: true`)
- `cancel_tiktok_decision` if the plan is abandoned

### Video components (hooks-first structure)

Batch-extracted labels on each video (`metadata.components`). Prefer structured `hook.type` over free-form opinions.

- "What hook type and funnel stage is video `[id]`?"
- "List MOFU videos with hook type `direct_question`."
- "Compare saves/1k by hook type for TOFU posts since `[date]`."

Pair with:

- `get_tiktok_video` — includes `components` when synced (`components_available`)
- `get_video_components` — same card + Studio/velocity join
- `list_videos_by_component` — filter by `hook.type`, funnel, CTA
- `analyze_components` — aggregate labels vs metrics (default group_by=`hook.type`)

Rules: never invent components if missing; never rank BOFU primarily by views; CTA success needs conversion metrics (not wired yet).

### Weekly hook A/B review ritual (legacy shorthand)

1. `get_tiktok_marketing_insights(limit=15, since=YYYY-MM-DD)` — winners by views, engagement, saves/1k (live metrics only; ignore view counts in `recipe-2026-06.md`)
2. `get_tiktok_video(video_id)` — full caption, transcript, hooks, comment questions
3. `record_ab_learning(pair_id, learning, winner_video_id)` — backward-compatible; prefer `approve_tiktok_insight` for new learnings
4. Commit next action with `log_tiktok_decision` when the team agrees what to film/repost

Pair with:

- `get_tiktok_strategy_brief`
- `list_open_decisions` / `log_tiktok_decision` / `record_decision_outcome`
- `get_tiktok_content_briefing`
- `get_tiktok_marketing_insights`
- `get_tiktok_video`
- `get_video_components` / `list_videos_by_component` / `analyze_components`
- `get_tiktok_cohort`
- `find_ab_tests` / `find_variant_groups`
- `draft_tiktok_insight` / `approve_tiktok_insight` / `list_tiktok_insight_drafts`
- `suggest_hook_repackage`
- `record_ab_learning` / `get_ab_learnings`
- `suggest_next_tiktok_angles`
- `search_knowledge` with `entity_type: marketing_playbook`
- `search_knowledge` with `entity_type: marketing_comment_digest`

## Outreach drafts (privileged)

- "Draft an outreach email to `[practitioner]` about `[topic]` — show me the text first before creating the draft."

Pair with:

- `draft_outreach_email` — **requires `confirmed: true`** after you approve subject and body. Creates a Gmail draft only; never sends.

Rules:

1. Always show draft text to the human first.
2. Only call the tool after explicit approval with `confirmed: true`.
3. Never send email automatically.

## Appointment availability

- "What HCA appointment slots are visible for `[practitioner name]` in the next two weeks?"
- "Summarize upcoming visible slots by practitioner."

Pair with:

- `get_appointment_availability`

## Weekly briefing

- "Give me the weekly DocMap intelligence briefing."
- "Summarize active clinic pipeline, outreach targets, recent content, and ingestion health."

Pair with:

- `get_weekly_briefing`

## Knowledge search (general)

- "Search DocMap knowledge for `[topic]` and cite your sources."
- "What do we know about laparoscopy patient questions from TikTok content?"

Pair with:

- `search_knowledge`

## Citation rules for the assistant

When answering from MCP tools:

1. Prefer `source_title` and `source_url` over internal UUIDs.
2. Quote only short snippets returned by tools.
3. Say clearly when data is missing or tables are empty.
4. Do not infer patient identities from metadata-only demand patterns.
5. Do not request or repeat full email threads or WhatsApp transcripts.

## Out of scope (for now)

- Raw patient conversation ingestion requires a separate privacy review.
- Carousel Supabase ingest is deferred (supervised, post master plan).
