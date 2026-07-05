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

### Weekly hook A/B review ritual

1. `get_tiktok_cohort(since=YYYY-MM-DD, sort_by="views", limit=50)` — recent batch + tiers
2. `get_tiktok_marketing_insights(limit=15)` — winners by views, engagement, and saves/1k
3. `find_ab_tests(since=YYYY-MM-DD, winner_by="views")` — hook A/B pairs; use `group_by_pair_id=true` for MRI-style clusters
4. `get_tiktok_video(video_id)` — full caption, transcript, hooks, comment questions
5. `suggest_hook_repackage(video_id)` — proposed hook swaps using top performers as reference
6. `record_ab_learning(pair_id, learning, winner_video_id)` — persist approved learning

Pair with:

- `get_tiktok_content_briefing`
- `get_tiktok_marketing_insights`
- `get_tiktok_video`
- `get_tiktok_cohort`
- `find_ab_tests`
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
