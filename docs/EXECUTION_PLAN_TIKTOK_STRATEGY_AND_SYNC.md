# Execution Plan — TikTok Strategy Memory, Insights & Data Freshness

**Created:** 2026-07-06  
**Status:** Phases 0–5 implemented locally; Phase 0.1 refresh running; **Railway redeploy** needed for prod MCP  
**Supersedes / extends:** `docs/EXECUTION_PLAN_TIKTOK_MCP.md` (Phases 1–4 complete)  
**Problem statement:** Claude gives strategy-blind suggestions and date-filtered cohorts return empty while TikTok has newer posts — the synced library lags the catalog by ~3 weeks.

---

## TLDR

1. **Fix data freshness first** — ingest catalog posts through July 2026, wire `post_datetime_utc` into `posted_at`, sync Supabase so `get_tiktok_cohort(since=…)` matches reality.
2. **Strategy brief in Supabase** — one assembled context (constitution + approved insights + changelog) Claude must load before suggestions.
3. **Variant groups (2–N videos)** — discover by segment alignment; record **hypotheses** from plain-English chat, not frozen hook text.
4. **Two approval gates** — approve insight → approved learnings; promote to constitution → manual edit of `content-instruction.md` only.

---

## What we already shipped (this session)

| Item | Status |
|------|--------|
| Whisper **segment alignment** for same-audio detection | ✅ `segment_align.py` |
| **Registry** expanded to 6 strict pairs (2 videos each) | ✅ `ab_pair_registry.json` |
| Registry validation (no A/B/C, no video reuse) | ✅ `ab_pair_registry.py` |
| Auto-detect: different calendar days, one partner per video | ✅ `detect_ab_pairs.py` |
| Multi-signal analysis script | ✅ `scripts/ab_pair_multisignal.py` |
| MCP Phases 1–4 (cohort, A/B, learnings, repackage) | ✅ prior commit |

**Known gap confirmed:** Dataset newest `posted_at` = **2026-06-14**; catalog newest = **2026-07-02**; **8 posts since 2026-06-26** not in Supabase.

---

## Design principles (agreed)

| Principle | Implication |
|-----------|-------------|
| Plain-English workflow | Claude **drafts** structured insights; user approves — no hypothesis forms upfront |
| Underperformers matter | Default analysis: why did X flop vs similar content? |
| Variant groups, not strict pairs | 2–N videos per group (`same_audio` / `same_topic`); accidental third match = variance signal |
| Don’t record exact B hook | Pairing = segment align; store **reasoning**, not hook fingerprint |
| Reference set, not one viral video | Rankings from **live** metrics; RECIPE = qualitative patterns only (stale figures) |
| Two gates | Approve insight ≠ promote to constitution |
| Supabase for Claude Desktop | Strategy brief + insights in Supabase; files generate content |

---

## Phase 0 — Fix library staleness (immediate) 🟥

**Goal:** Claude can pull “last N days” and see posts that actually exist on @docmap.

### 0.1 Pipeline refresh (ops)

```bash
cd marketing-pipeline   # or repo root with -m marketing_pipeline
python -m marketing_pipeline tiktok refresh --since 2026-04-20
python -m marketing_pipeline tiktok export
python -m marketing_pipeline tiktok sync-supabase
python -m marketing_pipeline tiktok sync-playbooks   # if brief/playbooks changed
```

**Acceptance:**

- [ ] `tiktok_marketing_dataset.json` newest `posted_at` ≥ 2026-07-02 (or latest catalog date after refresh)
- [ ] Supabase `content_posts` count ≥ catalog videos with usable transcripts (target: close 39 → ~50+ gap)
- [ ] `get_tiktok_cohort(since="2026-06-26")` returns ≥ 8 posts in prod MCP

### 0.2 Wire catalog datetime into dataset

**Problem:** `post_datetime_utc` exists in catalog JSON but `build_dataset()` uses `parse_master_transcripts` → midnight UTC only.

**Change:**

- In `orchestrator.build_dataset()`, set `posted_at` from `catalog[video_id].post_datetime_utc` when present, else fallback to parsed master date.
- In `write_master_transcripts`, include time in analytics block (optional display).
- Re-export + sync after code change.

**Acceptance:**

- [ ] No `posted_at` values stuck at `T00:00:00` when catalog has full timestamp
- [ ] Unit test: catalog datetime overrides midnight parsed date

### 0.3 Catalog-only posts (metadata without transcript)

**Problem:** New posts may appear in catalog before Whisper completes — invisible to `build_dataset()` entirely.

**Change (minimal v1):**

- On sync, upsert **catalog stub rows** for TikTok videos in catalog but not yet in dataset: `posted_at`, caption, metrics from catalog, `metadata.transcript_status: pending`.
- MCP `get_tiktok_cohort` includes stubs; `get_tiktok_video` flags incomplete transcript.
- Full enrich when `_COMPLETE` transcript lands.

**Acceptance:**

- [ ] Date filters never return 0 when catalog has posts in window (stubs OK)
- [ ] Claude message: “3 posts pending transcript” not “nothing published”

### 0.4 MCP staleness guardrails

**Change:**

- `get_tiktok_cohort` response adds `library_newest_posted_at`, `library_video_count`, `staleness_warning` when newest &lt; 7 days behind UTC today.
- Update `mcp_instructions.py`: never infer “channel stopped posting” from empty cohort — check staleness fields.

**Acceptance:**

- [ ] Empty cohort + old `library_newest_posted_at` → explicit warning in tool JSON

---

## Phase 1 — TikTok Strategy Brief (Supabase) 🟥

**Goal:** One tool loads everything Claude needs before creative suggestions.

### 1.1 Brief document schema

Store in Supabase (single row JSONB, e.g. `marketing_strategy_docs` or `content_posts` special row):

```text
meta: { updated_at, metrics_as_of, video_count, instructions_for_claude }
1_constitution      ← excerpt from content-instruction.md + viral-format.md
2_approved_patterns ← manually promoted rules (starts empty)
3_approved_insights ← Gate-1 approved learnings
4_open_drafts       ← pending insight cards
5_anti_patterns     ← from RECIPE + failures
6_changelog         ← append-only dated lines
reference_set       ← top N video_ids by views + saves/1k (live query at build time)
```

### 1.2 Build + sync

- New module: `marketing_pipeline/tiktok/stages/build_strategy_brief.py`
- Runs on: `tiktok export`, `sync-supabase`, `approve_insight` (Phase 2)
- Embeds brief body as `marketing_playbook` entity `tiktok-strategy-brief.md` for `search_knowledge` fallback

### 1.3 MCP tool

- `get_tiktok_strategy_brief()` — returns full structured brief
- MCP instructions: **call this before** `suggest_hook_repackage`, `suggest_next_tiktok_angles`, or “what should we film”

**Acceptance:**

- [ ] Brief includes constitution excerpt + approved insights + changelog
- [ ] `metrics_as_of` matches last sync timestamp
- [ ] RECIPE figures labelled historical; rankings use live cohort only

---

## Phase 2 — Insight workflow (draft → approve) 🟨

**Goal:** Capture reasoning from conversation without bureaucracy; constitution unchanged unless promoted.

### 2.1 Insight schema (Supabase)

Table or `metadata` collection `tiktok_insights`:

| Field | Notes |
|-------|--------|
| `insight_id` | uuid |
| `group_id` | slug, e.g. `surgical-photos` |
| `video_ids` | 2–N, discovered |
| `cluster_basis` | `same_audio` \| `same_topic` \| `manual` |
| `confidence` | high \| medium \| suggested |
| `what_we_tried` | plain English |
| `expectation` | Claude-drafted from chat |
| `outcome` | metrics summary + date |
| `learning` | one sentence |
| `playbook_themes` | tags only |
| `status` | draft \| approved \| promoted |
| `approved_by` / `approved_at` | audit |

### 2.2 MCP tools

| Tool | Purpose |
|------|---------|
| `draft_tiktok_insight` | Claude proposes card from chat + cohort data; status=draft |
| `approve_tiktok_insight` | User confirms → status=approved, append changelog, rebuild brief |
| `list_tiktok_insight_drafts` | Weekly review queue |
| `propose_constitution_patch` | Gate 2 only — returns markdown snippet for human to paste into `content-instruction.md`; **never auto-writes** |

Evolve `record_ab_learning` → alias or wrapper around `approve_tiktok_insight` for backward compatibility.

### 2.3 Suggestion tool contract

Update `suggest_hook_repackage` + `suggest_next_tiktok_angles`:

1. Load strategy brief (internal)
2. Load reference set from live cohort
3. If target video given → underperformer analysis vs variant group first
4. Output sections: **Playbook / Builds on / Hypothesis / Avoids**

**Acceptance:**

- [ ] User says “why did this flop?” → draft card → user says “approve” → appears in brief §3
- [ ] Constitution file untouched after Gate 1

---

## Phase 3 — Variant groups (evolve A/B model) 🟨

**Goal:** Replace strict-pair-only thinking with discoverable groups; keep registry for human-confirmed anchors.

### 3.1 Rename conceptually

| Old | New |
|-----|-----|
| `ab_pair_registry.json` | `variant_group_registry.json` (or keep file, allow 2–N `video_ids`) |
| `pair_id` | `group_id` |
| `find_ab_tests` | `find_variant_groups` (alias old tool) |

Relax registry validation: **2–4 videos per group**, still no duplicate video across groups.

### 3.2 Discovery

- Primary: segment alignment ≥ 0.73 + different calendar days
- Secondary: same_topic cluster (lower confidence) for manual review
- Auto-suggest groups → `open_drafts` in brief, not auto-approved

### 3.3 Migrate existing registry

- Current 6 pairs stay as 6 groups (2 videos each)
- MRI third clip stays out (different audio)
- Backfill `hypothesis` / `expectation` fields from existing `learning` text

**Acceptance:**

- [ ] 3-video cluster surfaces as suggested group with variance breakdown
- [ ] Tests updated for 2–N registry entries

---

## Phase 4 — Metrics & reference hygiene 🟨

### 4.1 Live figures only in tools

- `get_tiktok_marketing_insights`: add optional `since` filter (parity with cohort)
- Brief builder: stamp `metrics_as_of` from max `metadata.synced_at`
- Deprecate citing view counts from `recipe-2026-06.md` in MCP instructions

### 4.2 Reference set

- Top 5 by views + top 5 by saves/1k (deduped) injected into brief
- Explicit note when 360k lap video is one of many, not the sole template

### 4.3 Weekly cron alignment

- Ensure data-worker / manual weekly job: `refresh` → `export` → `sync-supabase` → `build_strategy_brief`
- Document in `docs/MCP_ONBOARDING.md` expected lag (&lt; 7 days)

**Acceptance:**

- [ ] After weekly job, `library_newest_posted_at` within 7 days of today

---

## Phase 5 — Docs & team workflow 🟩

- [ ] Update `docs/MCP_ONBOARDING.md` — strategy brief first, staleness warnings, insight approval
- [ ] Update `docs/mcp_prompt_guide.md` — underperformer-first ritual, draft/approve flow
- [ ] Update `EXECUTION_PLAN_TIKTOK_MCP.md` — pointer to this plan, Phase 5 items merged here

### Weekly ritual (revised)

1. `get_tiktok_strategy_brief()` — includes §7 decisions
2. `list_open_decisions(due_only=true)` — close due decisions first
3. `get_tiktok_cohort(since=<review_start>)` — check `staleness_warning`
4. Underperformers: “why did X flop?” → draft insights
5. `list_tiktok_insight_drafts` → approve in chat
6. Commit next actions → `log_tiktok_decision`
7. `find_ab_tests` / variant groups for new discovery
8. Later: `record_decision_outcome(..., confirmed=true)`
9. Optional: `propose_constitution_patch` (rare)

---

## Phase 6 — Decision log (AI conversation memory) 🟩

**Goal:** Forward loop after analysis — commit → review → outcome — stored for Claude, no UI.

| Tool | Purpose |
|------|---------|
| `log_tiktok_decision` | Human commits to an action in chat |
| `list_open_decisions` | Open / due queue |
| `get_tiktok_decision` | One decision by id |
| `record_decision_outcome` | Human-confirmed verdict (`confirmed=true`) |
| `cancel_tiktok_decision` | Abandoned plan |

Storage: `content_posts` strategy_state metadata `decisions[]` + brief §`7_decisions`. Sync merges MCP-written decisions so pipeline refresh does not wipe them.

**Non-goals:** no Next.js UI; no auto-verdict; no auto constitution promote; TikTok-only (`platform` ready for Instagram later).

---

## Implementation order (recommended)

| Order | Phase | Effort | Unblocks |
|-------|-------|--------|----------|
| 1 | **0.1** Ops refresh | S | Claude date queries work today |
| 2 | **0.2** Datetime wire-up | S | Accurate ordering within day |
| 3 | **0.4** Staleness warnings | S | Stops false “stopped posting” |
| 4 | **1** Strategy brief | M | Playbook-aware suggestions |
| 5 | **2** Insight draft/approve | M | Learning loop from chat |
| 6 | **0.3** Catalog stubs | M | No gap before transcript |
| 7 | **3** Variant groups | M | 3-video variance analysis |
| 8 | **4** Metrics hygiene | S | Fresh reference set |

**S** = small (hours), **M** = medium (1–2 days)

---

## Test plan

| Area | Test |
|------|------|
| Datetime | Catalog datetime flows to dataset `posted_at` |
| Cohort | `filter_by_date` with real timestamps; since=2026-06-26 returns &gt;0 after refresh |
| Staleness | Cohort tool emits warning when library newest &lt; threshold |
| Brief | Builder includes constitution + registry learnings |
| Insights | draft → approve → brief §3 + changelog |
| Registry | 2–N videos per group; no duplicate video_ids |
| MCP | `suggest_hook_repackage` fails soft without brief context (or loads automatically) |

---

## Out of scope (this plan)

- LLM comment labeling (deferred from prior plan)
- `sql/005` dedicated tables (JSONB sufficient until pain is real)
- Auto-promote insights to constitution
- Slack / internal chat ingest for hypothesis drafting (future)

---

## Success criteria

1. User asks “videos last 10 days” → Claude returns real posts or a **staleness warning**, never “you stopped posting.”
2. User discusses a flop in plain English → draft insight → approve → persists in Supabase brief.
3. Suggestions cite playbook theme + prior learning, not random top video mimicry.
4. Constitution changes only via explicit human promotion (Gate 2).

---

## Immediate next action

Run **Phase 0.1** (pipeline refresh + sync), then implement **0.2 + 0.4** in code so the fix survives the next export cycle.
