# Execution Plan — TikTok MCP & Hook A/B Workflow

**Created:** 2026-07-06  
**Completed:** 2026-07-06  
**Status:** ✅ Complete (Phases 1–4); Phase 5 deferred  
**Depends on:** Live `content_posts` sync (39 TikTok rows), `mcp-server` on Railway

## TLDR

Claude can now run the TikTok review ritual: multi-metric cohorts, full video-by-ID inspection, hook A/B pairs from a curated registry, hook repackage proposals (LLM), and recording approved learnings to Supabase.

## Critical Decisions

- **Supabase `content_posts` stays canonical** — no new tables in phase 1; extend `metadata` JSONB for learnings and pair groupings. Defer `sql/005_tiktok_marketing.sql` until JSONB query pain is real.
- **A/B pairs need human + tracker metadata** — transcript similarity does not match production reality. **Registry file** is source of truth; auto-detect remains a future helper (Phase 5).
- **Performance = multi-metric** — views, engagement, saves/1k exposed via `sort_by` and `rankings`.
- **LLM at MCP call time** — `suggest_hook_repackage` uses OpenRouter chat; comment labeling stays regex.
- **MCP `instructions` + richer tool docstrings** — shipped in `common/mcp_instructions.py`.

---

## Phase 1 — MCP ergonomics ✅

- [x] Server `instructions=` on FastMCP
- [x] `fetch_tiktok_posts` ordered; caption/transcript selected
- [x] `fetch_tiktok_post`, `rank_posts`, `cohort_medians`, performance tiers
- [x] `get_tiktok_video` tool
- [x] `get_tiktok_cohort` tool
- [x] Upgraded `get_tiktok_marketing_insights`, `get_content_performance`, `find_ab_tests`
- [x] Expanded tool docstrings in `main.py`

---

## Phase 2 — A/B pair truth ✅

- [x] `ab_pair_registry.json` with MRI + excision pairs
- [x] `detect_ab_pairs.py` reads registry (removed `KNOWN_PAIRS`)
- [x] `performance_tier.py` at sync → `metadata.performance_tier`
- [ ] **Deferred (2.2):** embedding-based auto-suggest pairs

---

## Phase 3 — Learning loop ✅ (core)

- [x] Structured `metadata.ab_learning` schema via `record_ab_learning`
- [x] `record_ab_learning` MCP tool (Supabase write)
- [x] `get_ab_learnings` MCP tool
- [x] Weekly ritual in `docs/mcp_prompt_guide.md`
- [ ] **Deferred (3.3):** auto-embed learnings into `marketing_playbook` on sync
- [ ] **Deferred (3.4):** promote evidence draft to approved playbook monthly

---

## Phase 4 — Hook repackage ✅

- [x] `suggest_hook_repackage` with OpenRouter `chat_completion`
- [x] Guardrails: truncated transcript, human-approve docstring

---

## Phase 5 — Optional (not started)

- [ ] LLM pass on top-20 comments per video
- [ ] `sql/005_tiktok_marketing.sql`
- [ ] Daily OCR for new videos only
- [ ] Content tracker `script_id` ingestion

---

## Test plan

- [x] Unit: `rank_posts`, `aggregate_ab_tests`, cohort medians (`mcp-server/tests/test_tiktok_tools.py`)
- [x] Unit: performance tiers + registry pairs (`marketing-pipeline/tests/test_performance_tier.py`)
- [x] Live smoke: `get_tiktok_video`, `get_tiktok_cohort`, `find_ab_tests` (4 edges)
- [x] TikTok sync: 39 rows updated with performance tiers (2026-07-06)
- [ ] Manual: Claude Desktop session with new MCP tools after Railway deploy
- [ ] Manual: `record_ab_learning` → `get_ab_learnings` round-trip in prod

---

## Deploy checklist

- [x] Code committed and pushed to `main`
- [ ] Railway `mcp-server` redeploy (auto on push)
- [ ] Set `OPENROUTER_CHAT_MODEL` on Railway if not using default
- [ ] Refresh Claude Desktop MCP connection

---

## Weekly workflow (MCP instructions)

1. `get_tiktok_cohort(since=<review_start>, sort_by="views")`
2. `get_tiktok_marketing_insights(limit=15)`
3. `find_ab_tests(since=<review_start>, winner_by="views")`
4. `get_tiktok_video(id)`
5. `suggest_hook_repackage(underperformer_id)`
6. `record_ab_learning(...)`
7. `get_ab_learnings()` + `get_tiktok_content_briefing`
