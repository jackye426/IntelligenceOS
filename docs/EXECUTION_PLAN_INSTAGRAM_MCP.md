# Execution Plan - Instagram Intelligence, MCP & Learning Loop

**Created:** 2026-07-11  
**Status:** Plan only - no implementation yet  
**Scope:** Reels + carousels + static posts  
**Primary goal:** Build the Instagram equivalent of the TikTok intelligence loop, adapted for Instagram formats and available metrics.

---

## TLDR

Use open-source ingestion first, not a paid third-party API by default.

Recommended stack:

1. **Instaloader** for public Instagram content: posts, reels, carousels, captions, comments, metadata, incremental profile updates.
2. **yt-dlp** for Reel media download when we need transcription or video component extraction.
3. **instagrapi** as a controlled experiment for owned-account insights: reach, saves, profile visits, follows, link taps, watch metrics.
4. Existing content tracker CSV as a historical/enrichment layer, not the production source of truth.

Mirror TikTok's architecture:

```text
fetch -> normalize -> analyze components -> export dataset -> sync Supabase -> MCP tools -> strategy brief -> insight/decision loop
```

But Instagram should be **format-first**, not video-first.

---

## Product Decisions

| Decision | Choice |
|---|---|
| Formats in scope | Reels, carousels, static posts |
| Historical source | Existing content tracker CSV, useful but not fully trusted |
| Fresh source | Open-source fetch pipeline, starting with Instaloader |
| Primary metric | Owned conversion metrics if available: follows, profile visits, link taps |
| Fallback primary metric | Engagement quality: saves, shares, comments, likes normalized by reach/views/followers |
| Paid third-party APIs | Fallback only if open-source route is unstable |
| Carousels | In scope from v1, not deferred |
| Stories | Out of scope for v1 unless needed later |

---

## Key Constraint

There are two metric layers:

### Public Metrics

Likely available through open-source/public extraction:

- likes
- comments
- views / plays for Reels, when exposed
- caption
- timestamp
- media type
- permalink
- carousel child media
- thumbnail / media URLs
- hashtags and mentions
- public comment text
- profile follower count

### Owned Insights

May require Meta Graph API, Instagram account auth, instagrapi, or manual export:

- reach
- impressions
- saves
- shares, if not public
- profile visits
- follows attributed
- external link taps
- average watch time
- skip rate
- Reel retention-style metrics

The system should work when owned insights are missing, and upgrade rankings when they are present.

---

## Data Model

Use existing `content_posts` with `platform='instagram'`.

Recommended normalized payload:

```text
platform: instagram
platform_post_id
post_url
posted_at
title
topic
format: reel | carousel | static
hook
caption
transcript
metrics
metadata
```

Recommended `metrics` shape:

```json
{
  "likes": 0,
  "comments": 0,
  "views": 0,
  "plays": 0,
  "reach": null,
  "saves": null,
  "shares": null,
  "profile_visits": null,
  "follows": null,
  "external_link_taps": null,
  "avg_watch_time_sec": null,
  "skip_rate": null
}
```

Recommended `metadata.instagram_components`:

```json
{
  "format": "reel",
  "cover_hook": "",
  "caption_opening": "",
  "topic": "",
  "content_bucket": "",
  "featured_person": "",
  "cta": "",
  "funnel_stage": "TOFU|MOFU|BOFU|unclear",
  "creative_pattern": "",
  "save_reason": "",
  "comment_theme": "",
  "visual_structure": "",
  "source_layers": ["instaloader", "content_tracker_csv"]
}
```

Carousel-specific component fields:

```json
{
  "slide_count": 0,
  "cover_claim": "",
  "slide_pattern": "checklist|myth_busting|before_after|patient_story|doctor_explainer|other",
  "final_cta": "",
  "saveability": "high|medium|low|unclear"
}
```

Reel-specific component fields:

```json
{
  "speaker": "",
  "audio_type": "original|trend|unknown",
  "transcript_status": "complete|pending|unavailable",
  "opening_line": "",
  "watch_metric_layer": "available|missing"
}
```

---

## Metric Ranking

Use the strongest available score, with graceful fallback.

### Tier 1 - Commercial Intent

Use when present:

```text
follows_per_1k_reach
profile_visits_per_1k_reach
external_link_taps_per_1k_reach
```

### Tier 2 - Quality Engagement

Use when reach is present:

```text
saves_per_1k_reach
shares_per_1k_reach
comments_per_1k_reach
engagement_per_1k_reach
```

Use when reach is absent:

```text
saves_per_1k_views_or_followers
shares_per_1k_views_or_followers
comments_per_1k_views_or_followers
engagement_per_1k_views_or_followers
```

### Tier 3 - Format-Specific

Reels:

```text
views
plays
avg_watch_time_sec
skip_rate
completion/retention metrics if available
```

Carousels/static:

```text
saves
shares
comments
engagement rate
```

### Default Ranking

If owned insights are missing:

```text
instagram_quality_score =
  weighted_comments
  + weighted_saves_if_available
  + weighted_shares_if_available
  + likes
  normalized by views, reach, or follower_count
```

---

## Phase 0 - Proof Of Data Access

**Goal:** Confirm what open-source tools can fetch for `@docmap`, and whether owned insights are accessible.

### 0.1 Instaloader smoke test

Use Instaloader to fetch recent `@docmap` media.

Acceptance:

- [ ] Last 20 posts fetched
- [ ] Reels included
- [ ] Carousels included with child media
- [ ] Static posts included
- [ ] Captions and timestamps present
- [ ] Like/comment/view fields mapped where available
- [ ] Comments can be fetched for selected posts

### 0.2 yt-dlp Reel media test

Use yt-dlp on 3 recent Reels.

Acceptance:

- [ ] Reel video downloadable
- [ ] Audio extractable
- [ ] Existing transcription flow can be reused or adapted

### 0.3 instagrapi owned-insights test

Use a controlled authenticated session for the DocMap account.

Acceptance:

- [ ] Can fetch media list safely
- [ ] Can fetch media insights for one Reel
- [ ] Can fetch media insights for one carousel/static post
- [ ] Confirm whether these exist: reach, saves, shares, profile visits, follows, link taps, watch metrics
- [ ] Document reliability concerns: login challenges, rate limits, session refresh, account safety

### 0.4 Content tracker enrichment test

Compare existing CSV rows to fetched public posts.

Acceptance:

- [ ] Match by IG post ID or permalink
- [ ] Determine which CSV fields fill owned-insight gaps
- [ ] Decide whether CSV remains manual enrichment or bootstrap-only

---

## Phase 1 - Instagram Pipeline Scaffold

**Goal:** Create a TikTok-like package shape for Instagram.

Target structure:

```text
marketing-pipeline/src/marketing_pipeline/instagram/
  orchestrator.py
  models.py
  stages/
    fetch_posts.py
    fetch_comments.py
    enrich_owned_insights.py
    import_content_tracker.py
    extract_reel_transcripts.py
    extract_components.py
    build_strategy_brief.py
  sync/
    supabase.py
```

Acceptance:

- [ ] `instagram fetch` writes raw JSON artifacts
- [ ] `instagram export` writes normalized dataset
- [ ] `instagram sync-supabase` upserts `content_posts(platform='instagram')`
- [ ] Embeddings created for captions, hooks, comments digest, and strategy docs
- [ ] Pipeline logs to `data_ingestion_runs`

---

## Phase 2 - Component Extraction

**Goal:** Add Instagram-specific content cards.

Inputs:

- caption
- caption opening line
- cover image / first carousel slide
- Reel transcript, if available
- comments summary
- content tracker fields, if matched

Outputs:

- `metadata.instagram_components`
- `metadata.performance_tier`
- `metadata.comment_themes`

Acceptance:

- [ ] Reels get hook/speaker/topic/CTA/funnel labels
- [ ] Carousels get slide-pattern/saveability labels
- [ ] Static posts get visual/message/CTA labels
- [ ] All posts get a normalized `funnel_stage`
- [ ] Components are stored in Supabase metadata

---

## Phase 3 - Instagram MCP Tools

**Goal:** Give Claude the same working surface it has for TikTok.

Initial tools:

| Tool | Purpose |
|---|---|
| `get_instagram_post` | Full post card: caption, format, metrics, components, comments |
| `get_instagram_cohort` | Date-filtered posts with freshness warning |
| `get_instagram_marketing_insights` | Multi-metric rankings by format |
| `get_instagram_strategy_brief` | Instagram playbook + approved learnings + decisions |
| `analyze_instagram_components` | Aggregate format/component labels vs performance |
| `suggest_next_instagram_angles` | Draft next post/reel/carousel ideas |
| `suggest_instagram_repackage` | Repackage a weak post into stronger format/hook |

Prefer platform-generic naming later:

```text
get_content_post(platform="instagram")
get_content_cohort(platform="instagram")
get_content_strategy_brief(platform="instagram")
```

Acceptance:

- [ ] Claude can answer "what worked on Instagram last week?"
- [ ] Claude can compare Reels vs carousels vs static
- [ ] Claude can cite post URLs and dates
- [ ] Empty recent cohort emits freshness warning, not false conclusions

---

## Phase 4 - Strategy Brief

**Goal:** Build Instagram memory, not one-off analysis.

Brief sections:

```text
0_meta
1_constitution
2_format_rules
3_approved_insights
4_open_drafts
5_anti_patterns
6_reference_set
7_decisions
8_changelog
```

Reference set:

- Top Reels by intent metric
- Top carousels by saves/shares/comments
- Top static posts by engagement quality
- Recent underperformers worth learning from

Acceptance:

- [ ] Brief includes metrics freshness date
- [ ] Brief includes per-format rules
- [ ] Brief separates live metrics from historical CSV notes
- [ ] Suggestions must load brief first

---

## Phase 5 - Insight & Decision Loop

**Goal:** Match TikTok's durable learning loop.

Tools:

| Tool | Purpose |
|---|---|
| `draft_instagram_insight` | Draft learning from post/group analysis |
| `approve_instagram_insight` | Human approves insight into brief |
| `list_instagram_insight_drafts` | Review pending insights |
| `log_instagram_decision` | Record committed next action |
| `list_open_instagram_decisions` | Review due decisions |
| `record_instagram_decision_outcome` | Close decision after metrics review |

Insight schema:

```json
{
  "insight_id": "",
  "platform": "instagram",
  "format": "reel|carousel|static|mixed",
  "post_ids": [],
  "cluster_basis": "same_topic|same_format|manual|same_campaign",
  "what_we_tried": "",
  "expectation": "",
  "outcome": "",
  "learning": "",
  "confidence": "high|medium|low",
  "status": "draft|approved|promoted"
}
```

Acceptance:

- [ ] User can discuss a post in plain English
- [ ] Claude drafts an insight card
- [ ] User approval persists the learning
- [ ] Future suggestions cite approved Instagram learnings

---

## Phase 6 - Weekly Review Ritual

Recommended workflow:

1. `get_instagram_strategy_brief()`
2. `list_open_instagram_decisions(due_only=true)`
3. `get_instagram_cohort(since=<review_start>)`
4. Review winners by format:
   - Reels
   - carousels
   - static posts
5. Review underperformers:
   - good topic, weak packaging
   - strong reach, weak intent
   - strong saves, weak follows/profile visits
6. Draft and approve insights
7. Commit next actions
8. Repackage top lessons into next filming/carousel plan

---

## Implementation Order

| Order | Phase | Effort | Why |
|---|---|---:|---|
| 1 | Phase 0.1 Instaloader smoke | S | Proves fresh public source |
| 2 | Phase 0.3 instagrapi insights test | S/M | Determines whether primary metric is possible |
| 3 | Phase 0.4 CSV enrichment map | S | Preserves valuable historical/private fields |
| 4 | Phase 1 scaffold | M | Creates stable pipeline |
| 5 | Phase 2 components | M | Makes analysis Instagram-native |
| 6 | Phase 3 MCP tools | M | Gives Claude usable interface |
| 7 | Phase 4 strategy brief | M | Adds memory |
| 8 | Phase 5 insight/decision loop | M | Closes learning loop |

---

## Risks

| Risk | Mitigation |
|---|---|
| Instagram blocks public scraping | Use conservative rate limits, session reuse, fallback to Apify/Bright Data |
| instagrapi triggers login challenges | Treat as optional owned-insights experiment; keep public pipeline independent |
| Owned insights unavailable | Rank by public/CSV metrics and mark missing fields clearly |
| CSV and fetched posts mismatch | Match by permalink/shortcode first, then timestamp/caption fallback |
| Carousels lose meaning if only first image fetched | Ensure child media extraction is a hard v1 requirement |
| Metrics are stale | Add `library_newest_posted_at` and `metrics_as_of` warnings |

---

## Success Criteria

1. Fresh Instagram posts appear in Supabase without relying on the content tracker CSV.
2. Reels, carousels, and static posts are all represented with format-specific components.
3. Claude can rank Instagram posts by the strongest available metric layer.
4. Claude can explain why a carousel/Reel/static post worked or failed.
5. Approved Instagram learnings persist and influence future suggestions.
6. If profile visits/follows are available, they become primary ranking signals.
7. If they are not available, the system falls back cleanly to engagement quality.

---

## Immediate Next Action

Run Phase 0 as a no-database, read-only spike:

```text
Instaloader: fetch last 20 @docmap posts
yt-dlp: fetch media for 3 Reels
instagrapi: test owned insights on 3 post types
CSV: match fetched posts to content tracker rows
```

Then decide whether Instagram v1 uses:

```text
public-only metrics
public metrics + CSV enrichment
public metrics + instagrapi owned insights
```

