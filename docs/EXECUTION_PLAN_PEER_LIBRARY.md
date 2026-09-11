# Execution Plan v2 — Peer library: audience engine (first subject `@drleewarren`)

**Created:** 2026-09-10
**Revised:** 2026-09-10 (v2 — code-verified; supersedes `EXECUTION_PLAN_PEER_LIBRARY.v1.md`)
**Status:** Plan only — not implemented
**Subject:** [tiktok.com/@drleewarren](https://www.tiktok.com/@drleewarren) (Dr Lee Warren) — **~1,372 posts**
**Depends on:** existing TikTok pipeline (catalog, Whisper, OCR, components; comments optional) + hosted MCP

---

## TLDR

Ingest `@drleewarren` as an **isolated peer library** and answer three questions:

1. How he **created an audience** (positioning, named promise, repeatable format, cadence, off-platform ladder).
2. **Why that engine works** from the posts themselves: content, hooks, length, cadence and performance over time.
3. What is **portable** so we can assign the same kind of success to **DocMap** and to a **clinic customer we sign** — instantiated in *their* specialty.

Two things changed in v2 and both are load-bearing:

- **The catalog is ~1,372 posts, and that is the asset.** It spans the acquisition era. A "60–80 most recent" cap would have contained zero evidence about how the audience was built. Ingest metadata for **all** of it; sample the expensive stages.
- **Isolation was asserted, not implemented.** Four code paths would corrupt or delete DocMap data on the first peer sync. These are now **P0 preflight blockers** with their own acceptance tests, ahead of any peer ingest.

The primary analysis corpus is the content itself. Comments are compiled separately and loaded only when a later question needs audience-response evidence. Playbook (`content-instruction.md`, `viral-format.md`) remains a later optional check for DocMap's own page only.

---

## Goal (locked)

We are studying a **clinician-creator operating system**, not a competitor endo account.

**Success looks like** a transfer brief a human can hand to an internal DocMap content assignment and to a newly signed clinic customer, grounded in Claude reading a representative body of the actual posts. It says: here is the audience engine, here is what to copy as mechanics, here is what is unique to him, here is the assignment template.

**Failure looks like** a list of his winning hook texts, a recommendation to post "self-brain surgery" or faith content, filtering every insight through "ask for operative photos", or **a confident causal claim about growth that the data cannot support**.

---

## Subject notes (why this person)

Dr Lee Warren: neurosurgeon, author, podcaster. Promise is named ("Self-Brain Surgery"): neuroscience + faith to rewire thinking. TikTok is likely **top of funnel** into podcast / book / Substack, not a closed content loop.

Topic overlap with DocMap (endometriosis patient-action) is near zero. That is useful: we are forced to extract **mechanics**, not steal themes.

At ~1,372 posts the catalog probably spans three or more years. That matters for every median we compute (see Inference limits).

---

## Inference limits (read before writing any conclusion)

This section exists so the analysis cannot overclaim. State these in the artefact itself.

**Every metric we can get is cross-sectional.** Views per post measure how a post landed on the follower base he already had. Nothing here separates a post that *acquired* followers from a post that *pleased existing ones*. We have no follower time series, no traffic source mix, no paid/organic split, no Studio retention.

**What we can legitimately do instead** (all from catalog metadata, no extra ingest):

- Order the full catalog by `posted_at` and treat it as a pseudo-time axis.
- Look for a **rising view floor** over time — the clearest available proxy for audience growth.
- Locate **breakout candidates**: early-timeline outliers well above their local neighbours.
- Detect **format, duration and cadence eras**, and when the CTA destination in captions changed.
- Compare hooks, topics, lengths and publishing frequency between breakout candidates and matched local controls.
- Optionally, if a later hypothesis needs it, compare commenter identity across eras as a weak proxy for audience *widening* versus a loyal core.

**Structural weaknesses that cannot be engineered away — name them in the brief:**

| Weakness | Consequence |
|---|---|
| n = 1 creator | Cannot separate transferable mechanics from his idiosyncrasy plus luck |
| Survivorship bias | He is the subject *because* he is big. We cannot see clinicians who ran the same playbook and stayed at 2k |
| No counterfactual | The portable/him-specific split is Claude's judgement, not a measurement |
| Deleted/archived posts invisible | Cadence from `posted_at` is a **floor**, not a rate |

**Therefore:** the transfer brief is labelled **hypotheses, not findings**. Each portable mechanic carries a confidence level and the observation that supports it. Nothing promotes to constitution from this run.

**Mitigations we will take:** add a second and third peer later, including a **mid-size** clinician account, so mechanics can be contrasted rather than only observed. Close the loop by running one portable mechanic as a DocMap A/B and writing the result back (see Falsifiability).

---

## Sampling design (the ~1,372-post answer)

Fetch the catalog **first**, plot the date histogram and the view-versus-time scatter, **then** finalise sample sizes. That one cheap step tells us where the growth inflection is and therefore what to sample.

| Layer | Coverage | Stages | Purpose |
|---|---|---|---|
| **A — Metadata** | **All ~1,372** | catalog fetch only | Cadence over time, rising view floor, format eras, caption CTA ladder. Carries section 1 |
| **B — Deep** | **~200 stratified** | media, Whisper, OCR, hook merge, components | Hook / authority / packaging analysis. Carries section 2 |
| **C — Comments (optional)** | **On demand** | comment fetch + generic labelling | Follow-up evidence for specific posts or hypotheses; not required for the first content analysis |

**Stratification for layer B:** split the timeline into neutral statistical segments (`era_1`, `era_2`, `era_3`) using the histogram, then sample by performance tier *within* segment. Never "most recent N"; that captures only the latest period. The pipeline must not name a segment "breakout" or "mature". Claude assigns semantic phase names only after inspecting monthly trends and underlying posts.

**The sample must be reproducible.** `sample-plan` writes a `sample_plan.json` recording the neutral segment boundaries, the per-segment and per-tier quotas, the RNG seed, the selected video ids and the catalog content hash it was derived from. Refresh, component extraction, sync and the manifest all read that file rather than re-deriving a selection. Re-running with the same seed and catalog reproduces the same 200 ids, so any conclusion can be traced to a named, regenerable sample.

**Cost at full scale, for reference (estimates).** These are why B is sampled and comments remain on demand:

| Stage | All 1,372 |
|---|---|
| Catalog + captions + public stats | 1 request, minutes |
| Media download | ~10–25 GB |
| Whisper `small`, CPU, 4 threads | ~15–25 hours |
| OCR vision calls | ~3,000–4,000 |
| Component extraction | 1,372 LLM calls (cheap) |
| Comment fetch (unauthenticated) | ~14,000 paged requests — **will be blocked; do not run by default** |
| Embedding rows written | several thousand |

Captions, public stats, post timestamps and duration arrive with the catalog fetch (`description`, metrics and `duration_sec` in `entry_to_row`), which is why layer A can be complete. Layer A is not merely an index: it is the full timeline Claude uses to reason about positioning, publishing frequency, duration mix, format eras and the rising performance floor.

### Missing values are null, never blank or zero

`entry_to_row` writes `""` for absent duration, views, likes, comments, shares and saves. A blank string reads as "present but empty" and silently satisfies any coverage check. Coerce empty strings to `None` at catalog write time and again at manifest build, and report per-field coverage counts. The no-zero-coercion rule in Age normalisation depends on this.

---

## Context budget (binding constraint)

At this catalog size the context window, not the pipeline, is the limiting resource. A manifest of 1,372 rows carrying full captions, full metrics, cadence fields and rolling medians runs roughly 200–350 tokens per row, so 275k–480k tokens by itself. Two hundred deep packets with full transcripts and timed segments add another 600–1,200 tokens each. Section 1 wants the whole timeline and section 2 wants the deep sample; as-is they cannot both be resident, and an overflowing session truncates silently with no record of which posts were dropped.

**The split is therefore fixed:**

| Payload | Contents | Rough budget |
|---|---|---|
| **Lean manifest, all ~1,372** | video_id, posted_at, duration_sec, public stats, per-1k ratios, cadence fields, rolling-local ratio, era, sample membership, coverage flags. **No captions, no titles, no transcripts** | ~40–70 tokens/row |
| **Era aggregates** | Computed server-side: posts per month, duration distribution, median and floor by era, CTA-destination counts. Replaces reading 1,372 captions to find eras | small, fixed |
| **Deep packets, ~200** | Full caption, full transcript, all hook channels, OCR text, component card, timed segments | 600–1,200 tokens each, batched 10–25 |
| **On-demand text** | Caption or transcript for any post Claude names outside the deep sample | per request |

Every paginated tool response must state total rows, rows returned, and the cursor, so a truncated read is visible rather than silent. If the deep sample cannot fit alongside the manifest, the manifest is dropped to era aggregates plus the sample rows, never the reverse.

---

## Age normalisation (new, required)

`performance_tier.py` medians **raw view counts** with no age adjustment. Across a three-year catalog that ranks "his winners" by how long each post has been live. Two fixes, both required for peer data:

1. **Rolling local median.** Compare each post against the median of its ~40 nearest neighbours in `posted_at`, not against the global catalog median.
2. **Stop coercing missing metrics to zero.** `compute_performance_tiers` turns an absent `save_count` into `0.0` and includes it in the median. Public peer catalogs often lack saves; that would collapse the saves median and mislabel most of the catalog. Missing must be `None` and **excluded** from the median, not floored.

**Window and boundary rules:**

- Window is 40 posts, centred: the 20 nearest earlier and 20 nearest later by `posted_at`.
- At the timeline edges the window slides inward rather than shrinking, so the first and last posts are compared against the nearest 40 neighbours available. Never compare a post against fewer than 40.
- Minimum viable window is 12 posts. Below that, emit `ratio: null` and `tier: "insufficient_window"` rather than a number.
- Every ratio carries `window_n` and the window's date span. The earliest era is sparse and low-view, which is exactly where breakout detection matters, so ratios there are noisy by construction and the brief must say so.
- Rolling ratios are computed over the **full** catalog, never over a filtered subset, so a date filter cannot change a post's tier.

Neither defect ever surfaced on DocMap because its catalog is ~70 posts and a few months old.

---

## P0 preflight — isolation blockers (fix and test BEFORE any peer ingest)

Each of these would corrupt DocMap data on the first `--account drleewarren` sync. v1 assumed all four already worked.

### 1. Peer sync deletes DocMap rows

`_prune_stale_tiktok` (`tiktok/sync/supabase.py:353`) selects **every** `content_posts` row where `platform='tiktok'` and deletes anything outside the current run's canonical id set, skipping only catalog stubs. A peer sync wipes the DocMap catalog.

**Fix:** prune must be scoped to the account being synced, and must refuse to run when the account filter is absent.

### 2. The scoping columns do not exist

- `owner_scope` was added to `document_embeddings`, **not** `content_posts` (`sql/004_mcp_sources.sql:25`).
- `account_handle` exists only on `tiktok_account_daily` and `tiktok_audience_snapshots` (`sql/005`).
- `content_posts` DDL is **not in the repo at all** — it lives only in Supabase.

**Fix:** new migration `sql/013_peer_libraries.sql` adding `account_handle TEXT NOT NULL DEFAULT 'docmap'` and `owner_scope TEXT NOT NULL DEFAULT 'docmap'` to `content_posts`, plus an index on `(platform, account_handle, posted_at DESC)`. Backfill existing rows to `docmap`. Also commit the current `content_posts` DDL so the schema is reviewable.

### 3. MCP reads are unscoped, and 1,372 rows displace DocMap entirely

`fetch_tiktok_posts` (`tools/tiktok_shared.py:29`) filters on `platform` only, caps at **500 rows**, and orders by `posted_at DESC`. With 1,372 peer posts in the table, DocMap's ~70 posts can be pushed **out of the window completely** — every DocMap cohort, briefing, components and A/B read would silently return peer data. `fetch_tiktok_post(video_id)` has no scope either, so `get_tiktok_video` would happily serve a peer video into a DocMap session.

**Fix:** `account` parameter on both fetch helpers, defaulting to `docmap`, applied as a SQL filter **before** the limit. Audit every caller: `get_tiktok_cohort`, `get_tiktok_video`, `get_content_performance`, `get_tiktok_marketing_insights`, `get_tiktok_content_briefing`, `get_tiktok_metric_layers`, `video_components.analyze_components` (also `limit=500`), `find_ab_tests`, `get_ab_learnings`, `tiktok_decisions`. Add a regression test asserting a DocMap cohort read returns zero peer rows with peer data present.

### 4. Peer embeddings poison the DocMap RAG store

`shared/embeddings.py:64` hardcodes `"owner_scope": "docmap"` on every chunk. The TikTok sync embeds the post, the transcript, and the comment digest **separately per video**. A peer ingest drops thousands of unfilterable peer chunks into DocMap retrieval. v1's isolation section never mentioned embeddings.

**Fix:** `owner_scope` becomes a parameter on `upsert_embedding_chunks`, threaded from the sync account. Peer runs write `peer:drleewarren`. `search_knowledge` filters to `docmap` by default.

Because comments are now an optional drill-down, the sync's per-video comment-digest embedding must also be **off by default for peer accounts**. It currently runs inside the same sync loop, so leaving it on would embed comment text the analysis never asked for.

---

## Pipeline work

### Account parameterisation

`config.py` resolves a single `DATA_ROOT` at import and exports **frozen module-level path constants** (`CATALOG_DIR`, `TRANSCRIPTS_DIR`, `OCR_CACHE_DIR`, and the rest) that around thirty stages read directly. A `--account` flag cannot redirect them as-is. Pick one:

- **(a) Preferred:** introduce an account-scoped paths object resolved per run and thread it through stage signatures.
- **(b) Interim:** document a per-invocation `MARKETING_DATA_DIR` override and make `--account` refuse to run if the resolved data root still points at the DocMap tree.

Either way, add a startup guard: peer account plus DocMap data root is a hard error.

### Hardcoded `@docmap` — five URL builders and four filename globs

- URLs: `fetch_catalog.py:13,46`, `download_media.py:13`, `parse_master_transcripts.py:55`, `write_comments_digest.py:46`, `sync/supabase.py:77` **and** `:238`.
- Filenames: `collect_catalog.py:11` globs `docmap_catalog_since_*.json`; also `refresh_stats.py:17`, `refresh_videos.py:51`, `refresh_legacy.py:41`.

All must take the handle. v1 named three of the five URL builders and none of the globs.

### Catalog fetch — capture the ladder and the denominator

`fetch_catalog` uses `--flat-playlist`, which discards uploader metadata. Two cheap additions with high analytical value:

- **Follower count at ingest** — the only available denominator for a reach-beyond-audience proxy. Without it, views cannot be normalised at all.
- **Bio text and link-in-bio** — the single most informative artefact for the off-platform ladder, and one fetch away. v1 inferred the ladder from captions only while ruling out any profile fetch.

### Component schema — versioned, not overwritten

`extract_components.SYSTEM_PROMPT` is hardcoded to DocMap endometriosis, and `FunnelStage` is a `Literal["TOFU","MOFU","BOFU","unclear"]` whose definitions are DocMap-specific (diagnosis / treatment / specialist / booking). v1 asked for awareness, how-it-works and product-CTA, which **changes the enum**.

- Add a `schema_version` and a **generic clinician-educator** prompt variant. Keep the hook vocabulary identical so hook mixes stay comparable; map funnel values through a documented crosswalk rather than silently redefining them.
- `_inputs_hash` does **not** include the prompt, so cached component cards will not invalidate when the prompt changes. Add a prompt fingerprint to the hash.

### Comment labelling — optional follow-up, replace before use

`analyze_comments.py:10-11` sets are endo-specific (`pouch_anatomy_question`, `imaging_mri`, `advocacy_what_to_ask`), and `THEME_PATTERNS` in `rebuild_comment_analysis.py` is an endo regex list. On his comments almost everything falls to `other_uncategorized`. This does not block the initial peer analysis because comments are not part of the default evidence packet, but the labeller must be replaced before any comment-led follow-up.

- Generic labeller: question / objection / personal-story / gratitude / off-topic, plus an "asks for a specific next step" flag.
- `structured_sentiment` (stance plus emotion) is generic enough to reuse unchanged.
- `transcript_utils.py:8-9` relevance regex is also an endo keyword list — check what it gates before running it on peer transcripts.

### Comment fetch — hardening required before optional use

`collect_comments.py` hits `tiktok.com/api/comment/list/` unauthenticated, with no backoff and no resume. It works at DocMap's ~70 videos. Before using comments for a targeted follow-up it needs exponential backoff, a persisted cursor so a blocked run resumes, and a per-run request budget. Do not attempt comments on all 1,372 and do not make comment completion a gate for the initial content brief.

### CLI (target)

```text
python -m marketing_pipeline tiktok fetch-catalog      --account drleewarren --since 2019-01-01
python -m marketing_pipeline tiktok sample-plan        --account drleewarren --deep 200
python -m marketing_pipeline tiktok refresh            --account drleewarren --from-sample-plan
python -m marketing_pipeline tiktok extract-components --account drleewarren --schema generic-clinician
python -m marketing_pipeline tiktok sync-supabase      --account drleewarren
python -m marketing_pipeline tiktok fetch-comments     --account drleewarren --video-id ID  # optional follow-up
```

`--account` is required on every peer command. Omitting it must not silently mean `docmap`.

---

## MCP work

- `account` parameter on all TikTok read tools, defaulting to `docmap`, applied before the row limit.
- `get_peer_corpus_manifest(account)` — new: **lean** catalog map, one row per post with video id, posted timestamp, duration, public stats, per-1k ratios, cadence fields, rolling-local ratio and window size, era, deep-sample membership and coverage flags. **Captions and titles are excluded by default** (see Context budget); `include_captions=true` is available for a bounded id list only. Paginated with stable ordering, no hidden top-performer filter, and every response states total, returned and cursor.
- `get_peer_era_summary(account)` — new: server-side aggregates so eras can be understood without reading 1,372 captions. Posts per month, duration distribution, median and view floor per era, CTA-destination counts.
- `get_peer_content_batch(account, video_ids, include=...)` — new: bulk evidence delivery for 10–25 selected posts per call. Returns full caption, full transcript, all three hook channels, duration, timestamps, metrics, deterministic cadence fields and optional component annotations. Claude can accumulate the complete deep sample across calls in one analysis context.
- `get_peer_comments(account, video_ids, cursor, limit)` — optional raw-comment drill-down. Never loaded by default and never required before the first transfer brief.
- `get_peer_library_brief(account)` — descriptive map only: era histogram, cadence over time, duration distribution, rolling medians, coverage and an explicit `not_measurable` block. It must not contain conclusions about what works or why; Claude produces those after reading the corpus.
- Prefer an MCP resource such as `peer://drleewarren/deep-sample.jsonl` for loading the immutable deep-sample corpus when the client supports resources. The batch tool remains the portable fallback.
- Server instructions gain the peer ritual: engine, then evidence, then portable versus specific, then assignment template. **Do not load the DocMap strategy brief until pass 3.**
- Do **not** expose on peer data: `suggest_hook_repackage`, `suggest_next_tiktok_angles`, `draft_tiktok_insight`, `log_tiktok_decision`, any constitution tool.

---

## Runtime evidence contract — exactly what Claude sees

Pass 1 is peer only. It starts with the complete catalog manifest, then loads every selected layer B post through stable deep-content batches or one corpus resource. Claude does not write the thesis until the selected content is in context. Pass 2 is the transfer write-up, using pass 1 evidence only. Pass 3 is optional, DocMap only, after the brief exists. Comments are a separate drill-down outside the default pass sequence.

**Catalog manifest row** (`get_peer_corpus_manifest`): video_id, title, full caption, post_url, posted_at, duration_sec, format, the full public metrics object, views, engagement total, saves/comments/shares per 1k views, days since previous post, posts in the same calendar week, rolling-local medians and ratios, era, sample membership, and evidence-coverage flags.

**Deep content packet** (`get_peer_content_batch`): everything above plus full caption, full transcript, timed transcript segments where available, spoken_hook, caption_hook, onscreen_hook, hook_source, OCR text, and the component card. Packets are returned in batches rather than requiring one tool call per video.

**On-screen text is opening-frames only, and usually fragmentary.** `extract_hook_frames` samples two or three frames at hook timestamps, so OCR covers the first seconds and nothing else. Every packet carries `ocr_scope: "opening_frames"` and the frame timestamps used. Consequently **pacing, mid-video captioning and edit rhythm are not in evidence** and no section may claim them.

Observed in the first live ingest: because TikTok captions animate word by word, a single frame catches mid-phrase, so the extracted values are fragments such as "THIS IS WHY" or "KILLS YOUR" rather than whole hooks. Roughly 8% of videos yield no on-screen text at all. **Use OCR as evidence of on-screen style, never as the on-screen hook text.** The spoken transcript and the caption are the two complete channels. Widening frame sampling and stitching fragments is the fix if this channel ever needs to carry weight.

**Component card, marked `derived_annotation`**: hook (text, channel, type from a fixed eleven-value vocabulary, emotional mechanism, specificity, target audience, creates_curiosity, contradicts_common_belief, payoff_clear, seconds_to_main_claim), claim and explanation blocks with timings, CTA (present, wording, position, channel, explicitness, urgency, requested action, value exchange), funnel_stage. Claude may disagree with these labels; they are not ground truth.

**Deterministic aggregates**: post counts by day/week/month, gaps between posts, duration distributions by era, rolling-local medians, metrics normalised per 1k views, library stats and staleness warnings. These are measurements, not conclusions.

**Interpretive boundary:** the pipeline may calculate dates, durations, cadence, ratios, rolling medians, sample membership and coverage. It must not pre-decide the recurring formats, psychological job of a hook, why a post worked, why an era grew, or which mechanics are portable. Those are Claude's analysis tasks after reading the underlying content.

**Optional comment packet** (`get_peer_comments`): raw comment text, likes, replies and timestamps for specifically requested videos. Comment labels may be included as annotations, but comment evidence is not loaded in passes 1 or 2 unless Claude or the human asks for it.

**Not provided and not to be claimed**: follower time series, demographics, paid versus organic, Studio retention or average watch time, Display velocity, Instagram, bookings or link-click conversion. Raw comments exist only through the optional drill-down and must not be implied to cover the whole library.

---

## Claude analysis product

One artefact, four sections. MCP supplies evidence; Claude writes the thesis. Nothing auto-promotes.

**Section 1 — Audience engine.** Who it is for, positioning line, repeatable formats with examples, cadence **over time** rather than a single average, duration mix and how it changes by era, owned ladder from bio and captions, and an explicit "what we cannot see" paragraph.

**Section 2 — Why it works.** Claude compares the actual content of winners and matched underperformers **versus rolling local median**: topic, format, duration, opening construction, spoken versus on-screen versus caption hooks, claim, explanation, CTA and recurring authority moves. It must cite representative posts and counterexamples. **Pacing and edit rhythm are out of scope** because OCR covers opening frames only. Comments are consulted only if a specific hypothesis needs audience-response evidence. Not ranked against DocMap or `viral-format.md`.

**Section 3 — Portable versus him-specific.** The transfer table, each portable item carrying a **confidence level** and its supporting observation.

| Portable (assign to DocMap *or* a signed clinic) | Him-specific (do not copy) |
|---|---|
| Clinician authority stated early | Neurosurgery / Iraq / OR stories |
| One **named** method or promise the brand owns | "Self-brain surgery" and faith frame |
| Repeatable series, not one-off explainers | His book and podcast titles |
| Shorts as TOFU into an owned next step | His Substack and podcast URLs |
| Cadence and talking-head packaging | His personal theology |

**Section 4 — Assignment template.** Fill-in fields, not scripts: positioning line `[clinician role] + [named promise] + [who it is for]`, two to four weekly series formats, cadence target scaled to what the customer can sustain, hook patterns as types and first-seconds jobs, CTA to an **owned** next step. Instantiation notes for DocMap (optional pass 3) and for a signed customer (their specialty, not DocMap endo rules).

---

## Falsifiability (new)

v1 ended at the template with no way to be wrong. Add one closing step:

- Pick the **single highest-confidence portable mechanic**.
- Register it as a DocMap A/B via the existing `detect_ab_pairs` and `record_ab_learning` machinery, with a written prediction and a review date.
- The peer brief is revisited when that outcome lands.

This is the only mechanism in the design that can ever downgrade a hypothesis.

---

## Locked decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Isolation | Separate data dir, schema columns, scoped MCP reads, scoped embeddings. **P0, tested before ingest** |
| 2 | Primary analysis | Audience engine plus transfer and assignment template |
| 3 | Sampling | All ~1,372 metadata and captions; ~200 deep, stratified by era; comments only on demand |
| 4 | Ranking | Rolling local median, age-aware; missing metrics excluded, never zeroed |
| 5 | Epistemic status | Transfer brief is **hypotheses with confidence levels**, not findings |
| 6 | DocMap playbook | Optional pass 3, DocMap only; never scores the peer |
| 7 | Instagram | Out of v1 |
| 8 | Owned metrics on the peer | Unavailable; say so; never invent retention |
| 9 | Constitution | Human-only, DocMap-only, after the transfer brief |
| 10 | Customer instantiation | Template is specialty-agnostic |
| 11 | Multi-peer | Out of v1 scope, but the **named** next step, including a mid-size account |
| 12 | Evidence priority | Content, hooks, duration, cadence and stats first; comments are an optional drill-down |
| 13 | Analysis ownership | Pipeline computes objective measurements; Claude interprets the underlying content |

---

## Out of scope (v1)

- Instagram duplicate ingest
- Automated "post this next week" calendar
- Promoting peer insights into `viral-format.md`
- Scraping his podcast or Substack as a second corpus (bio link plus captions are enough to detect the ladder)
- Multi-peer comparison UI
- Default full-library comment ingest or comment-led analysis

---

## Acceptance

**P0 isolation (must pass before ingest):**

- [ ] `sync-supabase --account drleewarren` deletes **zero** DocMap rows, tested with both libraries present
- [ ] Migration adds `account_handle` and `owner_scope` to `content_posts`; existing rows backfilled to `docmap`
- [ ] `get_tiktok_cohort()` with 1,372 peer rows present returns **only** DocMap posts and an unchanged median
- [ ] `get_tiktok_video(peer_id)` without an account argument does **not** return peer data into a DocMap session
- [ ] Peer embeddings land as `owner_scope='peer:drleewarren'`; `search_knowledge` defaults to `docmap`
- [ ] A peer run with the DocMap data root resolved is a hard error, not a warning

**Analysis:**

- [ ] Catalog count and date range confirmed, histogram reviewed, sample plan derived from it
- [ ] Every catalog manifest row exposes `posted_at`, `duration_sec`, full public stats and deterministic cadence fields, with missing values as null rather than `""` or `0`
- [ ] Lean manifest rows carry no captions or titles; a full-catalog manifest read plus the deep sample fits one context with headroom
- [ ] Every paginated response reports total, returned and cursor, so truncation is visible
- [ ] `sample_plan.json` reproduces the same deep-sample ids from the same seed and catalog hash
- [ ] Deep packets declare `ocr_scope: "opening_frames"`; no section claims pacing or edit rhythm
- [ ] Rolling ratios report `window_n`; posts below the minimum window return `insufficient_window`, not a number
- [ ] Layer B sample covers all statistical segments, not just recent posts
- [ ] Claude can load the complete layer B sample through stable 10–25 post batches or one MCP resource, without one-call-per-video discovery
- [ ] Deep packets contain full transcripts and all available hook channels, not only component labels or summaries
- [ ] Tiers computed against rolling local medians; missing-metric posts excluded, not floored
- [ ] Derived component labels are explicitly separated from raw evidence and may be challenged by Claude
- [ ] Artefact contains the four sections, an explicit limits section, and confidence levels on section 3
- [ ] Section 2 cites both supporting posts and counterexamples from the deep sample
- [ ] Assignment template is fill-in fields, not his scripts
- [ ] Signed-customer path does not require the DocMap constitution
- [ ] One falsifiable DocMap A/B registered with a prediction and review date
- [ ] Output rejected if it is only a hook leaderboard, or recommends faith-topic content
- [ ] Initial analysis completes without fetching comments; comments can be loaded later for named video ids

---

## Verification (after first ingest)

- Catalog count and date range for `@drleewarren`; follower count and bio captured
- Whisper, OCR and component coverage on the layer B sample, per era
- Manifest cadence calculations spot-checked against raw `posted_at` values; duration coverage reported
- Deep-sample resource or batches reconstruct the selected posts without truncating captions or transcripts
- Optional comment fetch, when invoked, completes within request budget and is cursor resumable
- `get_tiktok_cohort(account=docmap)` identical to a pre-ingest snapshot **except** the staleness fields, which `library_stats` recomputes from today's date. Compare the post id list and the medians, not the whole payload
- `document_embeddings` contains no `owner_scope='docmap'` rows referencing peer video ids
- One dry-run Claude session against the ritual
