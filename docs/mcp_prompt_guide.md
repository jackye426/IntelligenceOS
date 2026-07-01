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

Pair with:

- `get_tiktok_content_briefing`
- `get_tiktok_marketing_insights`
- `search_knowledge` with `entity_type: marketing_playbook`
- `search_knowledge` with `entity_type: marketing_comment_digest`

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

- `draft_outreach_email` is not enabled until privileged tools are explicitly turned on after review.
- Raw patient conversation ingestion requires a separate privacy review.
