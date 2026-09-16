# Feature Implementation Plan — Doctor-creator corpus (TikTok)

**Overall Progress:** `0%`
**Revised:** 2026-09-14 (v2 — code-verified and live-probed; supersedes the 2026-09-13 outline)
**Owner packages:** `marketing-pipeline` (collect), `gtm-pipeline` (link + customer handoff), `mcp-server` (read), `data-worker` (schedule)

## TLDR

Build a separate, resumable pipeline. It discovers a few thousand TikTok doctor-creators (US included), loads a small, fixed set of fields for each one, and splits them into two lanes:

- **Customer lane:** UK private-practice doctors who want to grow. They go **into the existing GTM system of record**: `gtm_clinic_intelligence`, then `gtm_clinic_people`, then `gtm_outreach_contacts`, under a new `tiktok_doctor_creators` cohort. Sales picks them up through the tools it already uses.
- **Research lane:** active doctor-creators of any geography. They stay in a **shallow research store** served to Claude through new MCP tools. A handful can be promoted into the existing peer-library pipeline.

Nothing touches `content_posts`, `document_embeddings`, the DocMap data tree or DocMap's own TikTok login.

v1's premise was reuse. Three live probes on 2026-09-14 showed that the reuse assumptions were wrong. The pipeline below is built around what actually works.

---

## Verified constraints (2026-09-14)

| Probe | Result | Consequence |
|---|---|---|
| `yt-dlp 2026.08.19`, `tiktok:tag` on `/tag/ukdoctor` | `_WORKING = False`; "No working app info is available"; `entries: [null]`, exit 0 | yt-dlp cannot do hashtag discovery. Keyword search was never supported |
| Logged-out headless Chromium on `/tag/ukdoctor` | Slider captcha ("Drag the puzzle piece into place"); `/api/challenge/item_list/` returns 200 with **zero items** | Browser discovery needs a logged-in session or a vendor API |
| `fetch_catalog --flat-playlist` profile metadata | `drleewarren_profile.json` is all nulls; a full single-video fetch returns `channel_follower_count = NA` | The current fetcher yields **no bio and no follower count** |
| Plain `GET https://www.tiktok.com/@handle` (no login) | HTTP 200; `__UNIVERSAL_DATA_FOR_REHYDRATION__` → `webapp.user-detail.userInfo` has `followerCount`, `heartCount`, `videoCount`, `signature` (bio), `bioLink.link`, `verified`, `isOrganization`, `commerceUserInfo`, `ttSeller`, `language`, `createTime`, `privateAccount`, `secUid`, `id` | **One cheap request per profile gets all the profile facts.** This becomes the profile fetcher |
| yt-dlp flat listing of a profile | Works: 262-post Warren ingest; throttles for minutes; returns null entries when throttled | Keep it for recent videos only, capped with `--playlist-end` |
| Live Supabase | `integrated_practitioners` **40,876** rows, **22,433 with `gmc_number`**; `gtm_clinic_people` 9,090; `gtm_clinic_intelligence` 1,513; `gtm_outreach_contacts` 734; `clinic_accounts` 1,683; `doctor_outreach` 115 | GMC-backed identity matching is available at scale |
| Live Supabase | `integrated_practitioner_with_phin` **does not exist** (PGRST205), but every `.env*` still sets `SUPABASE_PRACTITIONERS_TABLE` to it | Linking must target `integrated_practitioners`. Separately, MCP `search_practitioners` is probably broken. Fix outside this plan |
| `studio_listen.profile_dir()` | `DATA_ROOT/.tiktok_studio_profile` is DocMap's logged-in account | **Never** use it for discovery. Scraping on the owned account risks DocMap's page |
| DDL path | No working SQL connection (see memory `project-supabase`) | Every migration is applied manually in the Supabase SQL editor, then verified by script |

---

## Critical Decisions

1. **Two lanes, one store.** Every discovered account gets one row in `creator_profiles`, whatever its lane. Lane is a derived, re-computable field: `customer | research | both | discard | pending_review`.
2. **Customer rows are promoted into GTM, not copied into a parallel lead list.** Promotion creates or links `gtm_clinic_intelligence` (a solo practice is a clinic of size `solo`) and `gtm_clinic_people`. Contacts, cohorts, RocketReach, LinkedIn find and `list_ready_for_sales` then work unchanged.
3. **Promotion requires human review.** Scoring suggests; a person confirms. No auto-writes into outreach.
4. **Fixed shallow load per account** (see the load tiers below). No media, Whisper, OCR, components, comments, full catalogs or embeddings for the corpus.
5. **The LLM extracts; code decides.** The classifier returns labelled fields with verbatim evidence quotes. Lane and scores are deterministic functions, so rescoring never costs model calls.
6. **Missing is null, never zero.** This carries over from the peer postmortem. Score components with missing inputs are excluded, and `score_coverage` records what was used.
7. **Discovery is a pluggable adapter behind a gate.** Step 0 must prove a source before any volume work. Manual handle import exists from day one, so every later stage is buildable and testable without discovery.
8. **Every command writes counters** to `creator_crawl_runs`, including expected versus actual yields. A degraded run exits non-zero. This is postmortem lesson #1.
9. **A separate CLI channel with a table allowlist.** `python -m marketing_pipeline creators …` never calls `config.activate_account`, never imports `tiktok.sync`, and its store refuses writes outside `creator_*` tables.
10. **The follower band (5k–100k) is a customer score component,** never a discovery filter or a sort key.

---

## Architecture

```text
             ┌──────────────── DISCOVERY (Step 0-gated adapters) ─────────────────┐
 seeds ──▶   │ browser_session (research login) │ vendor_api │ manual CSV │ graph │ ──▶ creator_discovery_hits
             └────────────────────────────────────────────────────────────────────┘
                                   │ dedup on tiktok_user_id
                                   ▼
 creator_profiles (state machine)  discovered ─▶ profiled ─▶ screened ─▶ hydrated ─▶ classified ─▶ scored
                                   │               │            │            │             │           │
                                   │   profile_html GET    rules+bio   yt-dlp ≤23     LLM extract   deterministic
                                   │   (+snapshot row)     parse       (videos)       (+quotes)     lane + scores
                                   ▼                          │
                             excluded / unavailable ◀─────────┘
                                                                                                   │
            ┌──────────────────────────────────────────────────────────────────────────────────────┤
            ▼ customer | both (GB)                                                                  ▼ research | both
 gtm-pipeline creators link  ──▶ creator_links (practitioner/GMC, people, clinic domain)     MCP creator_corpus tools
            │  human review (MCP review_creator / CSV)                                     exports (CSV)
            ▼                                                                               │ human pick
 gtm-pipeline creators promote ──▶ gtm_clinic_intelligence + gtm_clinic_people                ▼
            ▼                                                                   creators promote-peer ──▶ existing
 segments refresh tiktok_doctor_creators ──▶ contacts refresh-outreach ──▶              peer-library pipeline
 rocketreach / linkedin-find (existing) ──▶ list_ready_for_sales (existing)            (tiktok --account X)
```

### Where the code lives

| Package | New module | Responsibility | Must not |
|---|---|---|---|
| `marketing-pipeline` | `src/marketing_pipeline/creators/` | seeds, discovery, profile fetch, screen, hydrate, classify, score, export, eval, drain | import `tiktok.sync`, `shared.embeddings`; call `activate_account`; write non-`creator_*` tables |
| `gtm-pipeline` | `src/gtm_pipeline/creators/` | link to practitioners/people/clinics; promote; cohort builder | write `creator_*` except link and promotion columns |
| `mcp-server` | `tools/creator_corpus.py` | read tools plus a confirmed review write | return creator rows from any `get_tiktok_*` or `get_peer_*` tool |
| `data-worker` | job in `main.py` | bounded nightly drain | run discovery via browser; run inside the 03:00–04:00 DocMap TikTok window |
| `sql/` | `014_creator_corpus.sql`, `015_gtm_creator_handoff.sql` | schema | alter `content_posts` or `document_embeddings` |

Local disk is a **cache**, not the system of record: `MARKETING_CREATORS_DATA_DIR`, default `marketing-pipeline/creators/data/`, gitignored. It holds:

- raw profile HTML blobs (gzipped JSON extract)
- raw listings
- the research browser profile `.tiktok_research_profile/`
- exports
- eval labels

Paths resolve **per call** (the postmortem #6 lesson). A test asserts the path differs from `studio_listen.profile_dir()` and from `config.DOCMAP_DATA_ROOT`.

---

## Load tiers — what gets fetched and what doesn't

| Tier | Applies to | Network cost | Data captured | Stored in |
|---|---|---|---|---|
| **0 Discovered** | every unique author found | 0 extra (arrives with the discovery page) | handle, tiktok_user_id, nickname, signature and follower count **if** the source includes them, hit video id, seed | `creator_discovery_hits`, `creator_profiles(stage=discovered)` |
| **Pre-screen** | Tier 0 from generic seeds | 0 | drop only when nickname **and** signature carry no medical signal at all. Practitioner-name and manual seeds always pass | `stage=excluded, excluded_reason=no_medical_signal_prescreen` |
| **1 Profiled** | all that pass pre-screen | 1 HTML GET | all `userInfo` fields in the table above | `creator_profiles`, plus 1 row in `creator_profile_snapshots` |
| **Screen** | all profiled | 0 (rules; batched LLM only for ambiguous bios) | doctor/brand/student/non-MD signals, bio parse (emails, links, cross-platform handles, geo and credential signals) | `creator_profiles.screen_*`, `bio_*` |
| **2 Hydrated** | screened-in, capped at 2–3k per cycle, highest seed priority first | 1 yt-dlp flat listing, `--playlist-end 23` | the latest ≤23 videos: posted_at, duration, views, likes, comments, shares, saves, caption, hashtags, @mentions, stitch/duet target | `creator_videos`, rollups on `creator_profiles` |
| **Classified** | all hydrated | 1 LLM call (cached on input hash) | doctor, role, specialty, country, practice setting, growth intent, formats, CTA types, each with verbatim quotes | `creator_assessments` |
| **Scored** | all classified | 0 | lane, customer_score, research_score, breakdown, coverage | `creator_profiles` |
| **3 Linked** | customer or both with GB geo | 0 (Supabase reads) | matches to `integrated_practitioners`, `gtm_clinic_people`, `gtm_clinic_intelligence`, `doctor_outreach` | `creator_links` |
| **4 Promoted** | human-confirmed customers | 0 plus optional existing enrichment jobs | GTM clinic, person, contact and cohort rows | GTM tables |
| **5 Deep peer** | a handful of human-picked research accounts | existing peer pipeline | full catalog, sampled Whisper/OCR/components | existing isolated peer library |

**Explicitly not fetched for the corpus:** media downloads, Whisper, OCR, component cards, comments, commenter lists, following or follower lists, per-video detail pages, full catalogs, embeddings of any kind, Instagram fetches (IG handles in bios are recorded, not followed).

**Pinned videos.** A flat listing can put old pinned posts first. Fetching 23 and computing every window by `posted_at` keeps posts/30d correct.

---

## Data model — `sql/014_creator_corpus.sql`

RLS follows `009`: `authenticated` may select, `service_role` may do everything. Every table carries `created_at` and `updated_at`.

### `creator_seeds` — what we search for
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| slice | text | `global \| uk \| practitioner \| graph \| manual`, used to enforce the 70/20/10 request budget |
| source_type | text | `hashtag \| keyword \| user_search \| graph_mention \| manual` |
| value | text | tag without `#`, search term, or a name for `user_search` |
| meta | jsonb | `{specialty_key, practitioner_id, gmc_number, from_creator_profile_id}` |
| priority | int | 0–100; hydrate order inherits max seed priority |
| status | text | `active \| exhausted \| blocked \| paused` |
| cursor | jsonb | adapter resume state |
| hits_total, unique_new_authors, doctor_yield, customer_yield | int / numeric | `doctor_yield` is backfilled after classification, **so bad hashtags are pruned on evidence** |
| last_run_at | timestamptz | |
| unique | (source_type, value) | |

### `creator_discovery_hits` — raw provenance of each find
`id, seed_id → creator_seeds, run_id → creator_crawl_runs, tiktok_user_id, handle, video_id, author_nickname, author_signature, author_follower_count (nullable), seen_at` — unique `(seed_id, tiktok_user_id)`.

### `creator_profiles` — one row per TikTok account (the hub)
| Group | Columns |
|---|---|
| Identity | `id uuid pk`, `tiktok_user_id text unique not null`, `sec_uid`, `handle text` (lower, indexed), `handle_history jsonb`, `profile_url` |
| Profile facts (latest successful fetch only) | `nickname, bio, bio_link, follower_count, following_count, heart_count, video_count, verified, is_organization, commerce_user, tt_seller, language, private_account, account_created_at, profile_fetched_at` |
| Discovery | `first_seen_at, seed_slices text[], best_seed_priority int, discovery_count int` |
| State machine | `stage` (`discovered \| profiled \| screened \| hydrated \| classified \| scored \| excluded \| unavailable`), `work_status` (`ready \| leased \| retry \| blocked`), `attempts, next_attempt_at, lease_owner, lease_expires_at, last_error, excluded_reason` |
| Screen and bio parse | `screen_result` (`doctor_signal \| ambiguous \| non_doctor`), `screen_reasons jsonb`, `bio_emails text[]`, `bio_links jsonb`, `bio_handles jsonb {instagram, youtube, x, linkedin, threads}`, `credential_signals jsonb`, `geo_signals jsonb`, `gmc_number_in_bio text` |
| Activity rollups (from `creator_videos`) | `recent_window_n, last_post_at, posts_30d, posts_90d, weeks_active_of_last_8, median_views, median_engagement_rate, median_duration_sec, views_to_followers_median, hydrate_status` (`complete \| partial \| blocked`), `hydrated_at` |
| Current assessment (denormalised from latest `creator_assessments`) | `assessment_id, is_doctor, doctor_confidence, doctor_role, specialty_raw, specialty_key, geo_country, geo_confidence, practice_setting, growth_intent_level` |
| Scoring | `lane, lane_reasons jsonb, customer_score, research_score, score_breakdown jsonb, score_coverage numeric, scoring_version, scored_at` |
| Review | `review_status` (`unreviewed \| confirmed \| rejected`), `review_lane_override, reviewed_by, reviewed_at, review_note, do_not_contact bool` |
| Promotion | `promoted_clinic_intelligence_id, promoted_person_id, promoted_at, peer_account_handle, peer_promoted_at` |
| Provenance | `provenance jsonb` |

Indexes: `(stage, work_status, next_attempt_at)`, `(lane, customer_score desc)`, `(lane, specialty_key, research_score desc)`, `(geo_country)`, `(review_status)`.

### `creator_profile_snapshots` — follower growth for free
`id, creator_profile_id, captured_at, follower_count, following_count, heart_count, video_count, source (profile_html | discovery_hit)`. Rows are only inserted on a **successful** fetch. Re-profiling every 30 days gives a real follower time series, which the Warren analysis could not have.

### `creator_videos` — the recent window only
`video_id text pk, creator_profile_id, url, posted_at, duration_sec, view_count, like_count, comment_count, share_count, save_count (all nullable), caption, hashtags text[], mentions text[], stitch_or_duet_of text, first_seen_at, metrics_updated_at`. Pruning keeps the latest 30 per profile, via a delete scoped to `creator_profile_id`.

### `creator_assessments` — LLM extraction with evidence
`id, creator_profile_id, classifier_version, prompt_fingerprint, model, input_hash, output jsonb, evidence jsonb [{field, quote, source: bio|nickname|caption:<video_id>}], quote_validation jsonb {checked, failed}, is_doctor, doctor_confidence, doctor_role, specialty_raw, specialty_key, geo_country, geo_confidence, practice_setting, growth_intent_level, content_formats text[], cta_types text[], created_at` — unique `(creator_profile_id, classifier_version, input_hash)`, which is the cache.

### `creator_links` — identity matches awaiting or past review
`id, creator_profile_id, target_table` (`integrated_practitioners | gtm_clinic_people | gtm_clinic_intelligence | doctor_outreach`), `target_id text, method` (`gmc_in_bio | email_exact | bio_domain | name_specialty | name_only | manual`), `confidence numeric, evidence jsonb, status` (`suggested | confirmed | rejected`), `reviewed_by, reviewed_at` — unique `(creator_profile_id, target_table, target_id)`.

### `creator_crawl_runs` — counters for every command
`id, command, source, params jsonb, status` (`running | completed | degraded | blocked | failed`), `budget jsonb {max_requests, deadline}, counters jsonb {claimed, requested, succeeded, not_found, private, blocked, partial, cached, llm_calls, quote_failures}, expectations jsonb {min_success_ratio}, worker, started_at, finished_at, error`.

### RPC `creator_claim(p_stage_from text, p_limit int, p_worker text, p_lease_seconds int)`
This copies `gtm_claim_job_items`:

1. Reclaim expired leases.
2. `FOR UPDATE SKIP LOCKED` on rows with `stage = p_stage_from AND work_status IN ('ready','retry') AND (next_attempt_at IS NULL OR next_attempt_at <= now())`, ordered by `best_seed_priority desc, first_seen_at`.
3. Set `work_status='leased'`.

### Views (the "organised output")
- **`creator_corpus_current`** — one lean row per scored profile: `handle, profile_url, nickname, specialty_key, doctor_role, geo_country, follower_count, posts_30d, median_views, median_engagement_rate, private_practice (practice_setting in private/mixed), growth_intent_level, lane, customer_score, research_score, score_coverage, review_status, promoted (bool), last_post_at, scored_at`. This is the original v1 output table.
- **`creator_customer_queue`** — lane `customer|both`, `do_not_contact = false`, not promoted, ordered by `customer_score desc`, with the best link joined.
- **`creator_research_board`** — lane `research|both`, ordered by `specialty_key, research_score desc`.

---

## Pipeline stages in detail

### Rate limiting, leases and circuit breaker (`creators/ratelimit.py`, `creators/runs.py`)
- **Token bucket per endpoint.** Initial values; Step 0 replaces them with measured ones.
  - `profile_html`: 1 request per 4–8 s with jitter
  - `listing`: 1 per 20–40 s
  - `browser_discovery`: 1 scroll per 3–6 s, ≤ 40 scrolls per seed
- **Block signals:**
  - HTTP 403/429
  - HTML without the rehydration blob
  - `statusCode` not in {0, 10202, 10221}
  - captcha text
  - listing with >20% null entries
- **Circuit breaker.** 5 consecutive block signals pause that endpoint for 30 min. A second trip ends the run with `status=blocked`, and claimed rows are released to `retry` with `next_attempt_at = now() + backoff`.
- **Budget.** `--max-requests` and `--deadline HH:MM` on every network command. The worker passes a hard 02:45 UTC deadline so DocMap's 03:30 TikTok jobs never share a throttled IP window.
- **Retry backoff:** `attempts` 1→15 min, 2→2 h, 3→24 h, then 4 sets `work_status=blocked` with `last_error` kept.
- **Run exit codes:** `0` completed; `2` degraded (success ratio below expectation); `3` blocked.

### 0. Seeds (`creators/seeds.py`)
- `creators seed-import --file seeds.csv` (`slice, source_type, value, priority, specialty_key`).
- `creators seed-practitioners --specialties obstetrics_gynaecology,fertility,menopause,endometriosis,ivf,dermatology --limit 1500`: builds `user_search` seeds from `integrated_practitioners` rows that have a `gmc_number` and a matching specialty, using `strip_person_title(name)` logic. `meta` carries `practitioner_id` and `gmc_number`, so any hit is linkable. **This replaces v1's unworkable "GTM name-match" and is the strongest UK customer route.** Specialty key mapping reuses `gtm_pipeline.segments.specialty.clinic_specialty_keys`. That is a gtm-pipeline function, so the seed builder shells out to `python -m gtm_pipeline creators export-practitioner-seeds` instead of importing across packages.
- Starter hashtag lists live in `creators/seeds/*.csv` under version control: global MedTok and specialty tags; UK tags (`ukdoctor`, `nhsdoctor`, `gpuk`, `privatedoctoruk`, `harleystreet`, city plus specialty); creator-behaviour tags (`doctorsoftiktok`, `learnontiktok` plus specialty).
- **Quotas are a request budget per slice** (`--slice-budget global=0.7,uk=0.2,practitioner=0.1`), not output guarantees.

### 1. Discovery (`creators/discovery/`)
Interface: `class DiscoverySource: def run(seed, budget) -> Iterator[DiscoveryHit]`, where `DiscoveryHit` is `tiktok_user_id, handle, nickname?, signature?, follower_count?, video_id?`.

| Adapter | How | Status |
|---|---|---|
| `manual` | `creators import-handles --file handles.csv --slice manual` | Build first; unblocks Steps 2–7 |
| `browser_session` | Playwright `launch_persistent_context` on **a dedicated research TikTok login** at `CREATORS_DATA_DIR/.tiktok_research_profile`. First run is headed, for a manual login. Intercepts `/api/challenge/item_list/`, `/api/search/user/full/` and `/api/search/general/full/` responses (the pattern of `studio_listen._attach_response_listener`) and parses `itemList[].author` / `authorStats` or `user_list[].user_info`. Captcha stops that seed with `status=blocked` | Step 0 candidate; local only |
| `vendor_api` | A third-party TikTok data API behind env `CREATORS_VENDOR`, `CREATORS_VENDOR_KEY`: hashtag posts, user search. Records cost per call in run counters | Step 0 candidate; worker-safe |
| `graph` | No network. Reads `creator_videos.mentions` and `stitch_or_duet_of` of the top 100 per lane and emits `graph_mention` seeds that resolve straight to handles | Step 8 |

Dedup key is `tiktok_user_id`. A handle that changed updates `handle_history`. A second hit from another seed increments `discovery_count` and merges `seed_slices`; it never re-queues a profile that is already past `profiled`.

### 2. Profile fetch (`creators/profile_fetch.py`)
- `GET https://www.tiktok.com/@{handle}` with a desktop UA and `Accept-Language: en-GB`, through `httpx` (already a dependency).
- Parse the rehydration blob, then `webapp.user-detail`.
  - `statusCode=0` → success.
  - `10202` (not found) or `10221` (banned) → `stage=unavailable`.
  - `privateAccount=true` → `stage=unavailable, excluded_reason=private`.
  - A missing blob or captcha is a **block signal, never "not found"**.
- On success: update profile facts, insert a snapshot, save the gzipped extract to cache, set `stage=profiled`. **On any failure, profile fact columns are left untouched** (postmortem #1: never overwrite good data with empty data).
- Tests use fixture HTML (success, private, not-found, captcha page, blob missing).

### 3. Screen and bio parse (`creators/screen.py`, `creators/bio_parse.py`)
Deterministic, versioned `SCREEN_VERSION`.

- **Exclude (`stage=excluded`):**
  - `is_organization`, or `commerce_user`/`tt_seller` without any doctor signal → `brand`
  - `video_count < 3` → `too_few_videos`
  - negative credential and no positive one → `non_medical_doctor`
  - student markers with no qualified signal → `student`
- **Positive signals** (word-boundary regex on nickname and bio): `dr`, `doctor`, `md`, `do`, `mbbs`, `mbchb`, `mrcp`, `mrcgp`, `frcs`, `frcog`, `frcr`, `frcpath`, `consultant`, `gp`, `surgeon`, `physician`, `resident`, `attending`, `board certified`, `gmc`, plus a specialty vocabulary.
- **Negative credentials:** `phd` (without an MD token), `dds`, `dmd`, `dentist`, `dc`, `chiropractor`, `dpt`, `physio`, `nd`, `naturopath`, `pharmd`, `dvm`, `vet`, `psyd`, `nurse`, `rn`, `np`, `pa-c`.
- **Student markers:** `med student`, `medical student`, `premed`, `ms1–ms4`, `fy1` (kept: FY doctors are qualified; tagged `doctor_role=junior`).
- **Ambiguous profiles** (no positive and no negative signal but medical words present) go to a batched cheap LLM micro-screen: 50 bios per call returning `{handle: yes|no|unclear, reason}`. `yes` and `unclear` proceed; `no` is excluded as `llm_prescreen_no`.
- **Bio parse output:**
  - emails
  - URLs, including `bio_link`, classified as `own_site | booking_platform (doctify, topdoctors, zocdoc, healthgrades, calendly) | linktree_like | social | other`
  - platform handles (`IG:`, `insta`, `YT`, `@x on YouTube`)
  - GMC number `GMC\s*(no\.?|number|#)?\s*:?\s*(\d{7})`
  - geo signals with weights: `.co.uk`/`.nhs.uk` domain 0.9; `NHS`, `GMC`, `MRCGP`, `FRCS`, `Harley Street` 0.8; UK city list 0.6; `£` 0.5; `UK` token 0.6; US state names/abbreviations with MD/DO 0.7; `board certified` 0.7; `$` 0.4

### 4. Hydrate (`creators/hydrate.py`)
- Extend `fetch_catalog.fetch_playlist` with `playlist_end: int | None = None` (it appends `--playlist-end`) and an `attempts` override. Existing callers are unchanged and a regression test covers `fetch_catalog`. Rows come from `entry_to_row(e, handle=handle)`, which already emits null for missing metrics.
- Hashtags and mentions are parsed from the caption. `stitch_or_duet_of` comes from `#stitch with @x` / `#duet with @x` patterns.
- **Partial listing:** if >20% of entries are null, set `hydrate_status=partial`, upsert the videos that did parse, leave rollups **null** and set `work_status=retry`. An all-null listing is a block signal, with no writes at all.
- **Rollups** (`creators/rollups.py`), all computed by `posted_at` over the parsed window:
  - `posts_30d`, `posts_90d`, `last_post_at`, `weeks_active_of_last_8`
  - `median_views` (nulls excluded)
  - `median_engagement_rate = median((likes+comments+shares)/views)` over videos with views > 0
  - `median_duration_sec`
  - `views_to_followers_median`
  - `recent_window_n`

  If the window reaches 23 videos but 90 days is not covered, `posts_90d` is a floor and is flagged in `lane_reasons`.

### 5. Classify (`creators/classify.py`, `creators/prompts/classify_v1.md`)
- Model `MODEL_CREATOR_CLASSIFY`, defaulting to `config.MODEL_COMPONENTS`, through `shared.openrouter_client.chat_completion` (empty-response retry is already built in). `max_tokens` is 1500.
- **Input:**
  - nickname, bio, bio link domain and class
  - the deterministic screen and geo signals
  - rollups
  - up to 23 captions truncated to 300 characters, each prefixed `[video_id]`
- **Output** (pydantic-validated, `extra=forbid`):
  - `is_doctor`, `doctor_confidence 0–1`
  - `doctor_role`: `gp | consultant | surgeon | junior | resident | attending | other_md | unknown`
  - `specialty_raw`, `geo_country` (ISO-2 or `unknown`), `geo_confidence`
  - `practice_setting`: `nhs | private | mixed | us_practice | academic | unknown`
  - `growth_intent_level 0–3` (level definitions below)
  - `content_formats` from a fixed vocabulary: `talking_head_explainer, myth_busting, day_in_life, patient_story, reaction_stitch, q_and_a, numbered_series, procedure_or_demo, trend_skit, news_commentary`
  - `cta_types` from a fixed vocabulary: `book_consult, link_in_bio, dm, newsletter, podcast_or_book, product, course, none`
  - `evidence: [{field, quote, source}]`
- **Growth intent levels:** 0 none visible. 1 brand-building only (generic link or following others). 2 practice promotion (own clinic site or booking platform link, services named, "private practice"). 3 an explicit booking or enquiry CTA ("book a consultation", "appointments available", "DM to book", booking URL).
- **Quote validation:** each `quote` must appear, whitespace-normalised and case-insensitive, in its declared source. Failed quotes are dropped and counted. If `is_doctor`, `geo_country` or `growth_intent_level` loses all support, that field is set to `unknown`/null and the profile gets `lane=pending_review`.
- `specialty_key` is mapped by gtm's specialty normaliser through the exported mapping table `creators/specialty_keys.json`, generated by `gtm_pipeline creators export-specialty-map` so the vocabularies stay identical.
- Cache: skip the call when `(classifier_version, input_hash)` already exists.

### 6. Score and lane (`creators/score.py`, `SCORING_VERSION`)
Re-runnable with no network or LLM: `creators score --all`.

**Lane rules**, in order:
1. `stage=excluded/unavailable`, or `is_doctor=false`, or `doctor_confidence < 0.6` → `discard` (reason carried).
2. `active` = `posts_90d >= 3 AND last_post_at >= now()-120d`.
3. `research_eligible` = `active AND follower_count >= 1000`.
4. `customer_eligible` = `geo_country='GB' AND geo_confidence >= 0.7 AND practice_setting IN ('private','mixed') AND video_count >= 3 AND NOT do_not_contact AND no doctor_outreach link with status='dnc'`. An inactive UK private doctor **is** eligible, because low output with growth intent is a sales angle.
5. The lane is `both`, `customer`, `research` or `discard` accordingly.
6. It becomes `pending_review` instead when `0.6 <= doctor_confidence < 0.8`, or when a customer signal is present with `0.5 <= geo_confidence < 0.7`.
7. `review_lane_override` wins when `review_status=confirmed`.

**customer_score (0–100)**; a null component is excluded and `score_coverage` = weight used / 100:
| Component | Weight | Rule |
|---|---|---|
| Growth intent | 30 | level 0/1/2/3 → 0/10/20/30 |
| Commercial fit | 25 | specialty tier A (`obstetrics_gynaecology, fertility, menopause, endometriosis, ivf` — the GTM priority keys in `sql/011`) 15, tier B (`dermatology` plus others configured) 10, other 5; plus practice setting private 10 / mixed 6 |
| Audience band | 15 | followers 5k–100k → 15; 2k–5k or 100k–250k → 8; otherwise 3 |
| Engagement | 15 | `median_engagement_rate` ≥6% 15, 3–6% 10, 1–3% 5, else 0; null if fewer than 5 videos with views |
| Contactability | 15 | email (bio or confirmed link) 15; own site or booking link 8; IG/LinkedIn only 4; none 0 |

**research_score (0–100):**
| Component | Weight | Rule |
|---|---|---|
| Cadence | 25 | `posts_30d` ≥12 25, 6–11 18, 3–5 10, 1–2 4 |
| Reach efficiency | 30 | percentile of `views_to_followers_median` **within the follower band** (<10k, 10–100k, 100k–1M, >1M) across the scored corpus × 30; null if the band has fewer than 30 profiles |
| Consistency | 15 | `weeks_active_of_last_8` / 8 × 15 |
| Format signal | 15 | any `content_formats` value recurring in ≥3 captions → 15; one recurring series marker (`part \d`, `day \d`, numbered) → 10 |
| Funnel signal | 15 | owned next step (`newsletter, podcast_or_book, course, book_consult`) 15; `link_in_bio` 8 |

`score_breakdown` stores each component's input, points and rule id, so any rank can be explained in one read.

### 7. Link — `gtm-pipeline/src/gtm_pipeline/creators/link.py`
Command `python -m gtm_pipeline creators link [--lane customer,both] [--dry-run]`. Only GB-lane profiles; US profiles are never linked.

In-memory indexes are built once per run, paged 1,000 at a time:
- `integrated_practitioners` by `gmc_number`, normalised email(s), `person_name_key(name)` and website domain
- `gtm_clinic_people` by name key and email
- `gtm_clinic_intelligence` by website domain
- `doctor_outreach` by `practitioner_id`

| Method | Rule | Confidence | Default status |
|---|---|---|---|
| `gmc_in_bio` | bio GMC number = `integrated_practitioners.gmc_number` | 0.99 | confirmed |
| `email_exact` | bio email ∈ practitioner `email/emails` or `gtm_clinic_people.email` | 0.95 | confirmed |
| `bio_domain` | `bio_link` own-site domain = clinic `website_url` or practitioner `website` domain | 0.90 | suggested |
| `name_specialty` | `person_name_key(nickname before "\|" or emoji)` equals the name key **and** specialty key overlap | 0.75 | suggested |
| `name_only` | name key equal, no specialty evidence | 0.50 | suggested; never used by promotion unless confirmed |

Multiple candidates at the same top confidence → all stay `suggested` and `evidence.ambiguous=true`. A practitioner link also backfills `doctor_outreach` state: `dnc` sets `do_not_contact`, and `converted` is added to `lane_reasons` as `existing_relationship`.

### 8. Review
- MCP `review_creator_tool(handle, decision, lane_override?, link_ids_confirm?, link_ids_reject?, note?, confirmed=false)`. Without `confirmed=true` it returns a preview only; this matches `draft_outreach_email`'s pattern.
- A CSV round-trip for bulk review: `creators review-export --queue customer --limit 200`, then `creators review-import --file reviewed.csv`. Columns: `handle, decision (confirm|reject), lane_override, link_confirm, link_reject, do_not_contact, note`.

### 9. Promote to GTM — `gtm-pipeline/src/gtm_pipeline/creators/promote.py`
Command `python -m gtm_pipeline creators promote [--handle X | --all-confirmed] [--dry-run]`. It is idempotent. For each profile with `review_status=confirmed`, lane `customer|both` and not `do_not_contact`:

1. **Resolve the clinic:**
   - a confirmed link to `gtm_clinic_intelligence` → use it
   - else a confirmed practitioner link whose website domain matches a clinic → use that
   - else look up by `source_creator_profile_id`
   - else **create** `gtm_clinic_intelligence`:
     - `clinic_name` = practice name from the bio or site title if present, else `"{Dr name} — private practice"`
     - `website_url` = `bio_link` when the class is `own_site`; booking links go to evidence
     - `email` = bio email, `visible_clinic_size='solo'`, `specialties=[specialty_key]`
     - `evidence=[evidence_item(kind='tiktok_profile', …), …]`
     - `provenance=make_provenance(source='creator_corpus', lane='tiktok_creator', source_url=profile_url)`
     - `source_creator_profile_id`
2. **Resolve the person:** a confirmed link to `gtm_clinic_people`, or a name match inside that clinic, or insert `{full_name, role: 'founder' if created solo clinic else 'specialist', specialty, email (bio → practitioner email), priority = round(customer_score), social_profiles, creator_profile_id, evidence, provenance}`. On an existing person, only `social_profiles` and `creator_profile_id` are set; email is filled only if empty.
3. **Write back** `promoted_clinic_intelligence_id`, `promoted_person_id` and `promoted_at`.
4. **Refresh the cohort:** `segments.refresh_cohort('tiktok_doctor_creators')` (builder branch below).
5. **Refresh contacts:** `refresh_outreach_contacts(cohort='tiktok_doctor_creators', cqc_named_only=False)`. **`cqc_named_only` must be False**, because the default `True` skips every creator clinic without CQC names.
6. **Enrichment (optional, existing):** `gtm-pipeline contacts rocketreach --cohort tiktok_doctor_creators` and `contacts linkedin-find --cohort tiktok_doctor_creators`.

**Duplicate-clinic guard.** A later Doctify sync upserts on `doctify_url` and could create a second row for the same practice. `creators link --recheck` compares website domains between `source_creator_profile_id` rows and Doctify rows. Each collision becomes a `gtm_match_reviews` row with `dedupe_key = 'creator_clinic:' || creator_profile_id`, for a human merge. Nothing merges automatically.

**Sales handoff (no new UI):** `gtm-pipeline contacts list --status ready` and `list_ready_for_sales()` now include creator contacts. `gtm_outreach_contacts.evidence` carries the sales angle: `handle, profile_url, follower_count, posts_30d, growth_intent_level + quote, specialty_key, top 3 video URLs by views, customer_score, score_breakdown summary`.

### 10. GTM schema and code changes — `sql/015_gtm_creator_handoff.sql`
- `gtm_clinic_intelligence.source_creator_profile_id uuid` with a unique partial index `WHERE source_creator_profile_id IS NOT NULL`.
- `gtm_clinic_people.creator_profile_id uuid` (indexed) and `gtm_clinic_people.social_profiles jsonb NOT NULL DEFAULT '{}'`.
- Extend the `gtm_outreach_contacts.email_source` CHECK with `'tiktok_bio'`. Use the constraint-swap `DO` block pattern from `012`.
- Seed cohort `tiktok_doctor_creators`: rules `{"source": "creator_corpus", "require_people": true}`, priority 85.
- **Code:**
  - `segments.refresh_cohort` gets a builder branch: when `rules.source == 'creator_corpus'`, members are clinics with `source_creator_profile_id` **or** a person with `creator_profile_id`. Without it, the generic delete-and-rebuild would **empty this cohort** on every `segments refresh`.
  - `contacts.pic.infer_email_source` returns `'tiktok_bio'` when the person's provenance source is `creator_corpus` and the email equals a bio email.
- Solo creator clinics that also satisfy the rules of existing cohorts (e.g. `solo_og_fertility`) will appear there too. **That is intended.**

### 11. MCP — `mcp-server/tools/creator_corpus.py`, registered in `main.py`
All list tools are paginated and return `total_rows, returned_rows, next_cursor`.

| Tool | Purpose | Returns |
|---|---|---|
| `get_creator_corpus_summary_tool()` | start here | counts by stage, lane, geo, specialty and review status; last 10 run counters; seed yields; coverage |
| `list_creators_tool(lane, geo_country?, specialty_key?, min_score?, follower_min?, follower_max?, review_status?, order=customer_score\|research_score\|followers\|posts_30d, cursor, limit≤100)` | browse lanes | lean `creator_corpus_current` rows |
| `get_creator_profile_tool(handle)` | one creator in full | profile facts, snapshots, rollups, assessment with **validated quotes**, score breakdown, links, latest videos with captions, promotion state |
| `compare_creators_tool(handles ≤10)` | research side-by-side | rollups, formats, CTA types, scores |
| `list_creator_seeds_tool(order=doctor_yield)` | which searches are worth running | seed yield table |
| `review_creator_tool(…, confirmed=false)` | human-confirmed review write | preview, or written review |

The MCP instructions (`common/mcp_instructions.py`) gain a **Creator corpus** section:
- The corpus is observed public data, and assessment fields are derived annotations that may be wrong.
- Customer outreach happens through GTM contacts, never directly from the corpus.
- Never pass creator handles to `get_tiktok_*`.
- A deep analysis of a creator requires `promote-peer` and then the existing `get_peer_*` ritual.
- Do not draft outreach to a `pending_review` or unconfirmed profile.

`/health` adds `creator_corpus_surface: "v1"`.

### 12. Exports and eval
- `creators export --view corpus|customer|research --format csv [--specialty-key K] [--lane L]` writes to `CREATORS_DATA_DIR/exports/{view}_{YYYYMMDD}.csv`, plus a header row and `docs/CREATOR_CORPUS_DATA_DICTIONARY.md` generated from the view columns.
- `creators eval --labels creators/eval/labels_v1.csv`. The labels file is **150 hand-labelled profiles**: ~60 UK, ~60 US, ~30 non-doctor lookalikes, with columns `handle, is_doctor, geo_country, practice_setting, growth_intent_level, lane`. Output: precision and recall per field, plus a confusion matrix for lane, saved to `creators/eval/results/{classifier_version}.json`.
- **Gate before promotion is enabled:** `is_doctor` precision ≥ 0.95, GB precision ≥ 0.90 among predicted GB, customer-lane precision ≥ 0.85.

### 13. Deep peer promotion
Command `creators promote-peer --handle X`. It requires `review_status=confirmed`, lane `research|both`, and no existing `peer_account_handle`. It prints and, with `--run`, executes the existing sequence (`tiktok fetch-catalog --account X`, `sample-plan`, `refresh --from-sample-plan`, `extract-components --schema generic-clinician`, `sync-supabase --account X`), then sets `peer_account_handle`. The existing peer release gate in `PEER_INGEST_POSTMORTEM.md` still applies unchanged.

### 14. Worker — `data-worker/main.py`
- `creator_corpus_drain`: daily at 01:00 UTC with a hard deadline of 02:45, behind `SKIP_CREATOR_CORPUS` (**default `true`**). It runs `creators drain --profile-max 400 --hydrate-max 120 --deadline 02:45`: profile → screen → hydrate → classify → score. Then `gtm_pipeline creators link` (no promotion). Browser discovery never runs on the worker; vendor discovery runs only if `CREATORS_VENDOR` is set.
- `creator_corpus_refresh`: Sundays at 00:30 UTC. Re-profiles lanes `customer|both|research` whose `profile_fetched_at` is older than 30 days (top 500 by score), and re-hydrates the top 200 older than 30 days.
- The volume path is `CREATORS_DATA_DIR` under `MARKETING_DATA_DIR/../creators`. A startup assertion checks it is not inside `DOCMAP_DATA_ROOT`.

### 15. Data governance
- Collect public profile data only. The customer lane is personal data of identifiable professionals, used for B2B outreach under legitimate interest. This needs to be recorded in `docs/` and signed off before M6.
- **Retention:** `discard` rows keep `tiktok_user_id, handle, excluded_reason, first_seen_at`. `bio`, captions and videos are purged after 90 days by the `creators purge` command in the weekly job, so rediscovery skips them cheaply.
- `do_not_contact` is honoured at promotion, and `doctor_outreach.status='dnc'` propagates through linking.
- The research browser login is a dedicated account, never DocMap's.

---

## Isolation and integration tests

| Test | Asserts |
|---|---|
| `test_creators_store_allowlist` | writing any table outside `creator_*` from the creators package raises |
| `test_creators_never_touch_docmap_tables` | a full `drain` with a mocked client makes zero calls to `content_posts`, `document_embeddings`, `tiktok_*` or `content_metric_snapshots` |
| `test_creators_do_not_activate_account` | `config.ACCOUNT` and `config.DATA_ROOT` are unchanged after every command |
| `test_research_profile_is_not_studio_profile` | `.tiktok_research_profile` path ≠ `studio_listen.profile_dir()` and is outside `DOCMAP_DATA_ROOT` |
| `test_docmap_tree_unmodified` | mtimes and file list of the DocMap data root are identical before and after a fixture drain |
| `test_profile_fetch_{success,private,not_found,captcha,no_blob}` | state transitions; profile facts untouched on failure; snapshot only on success |
| `test_hydrate_partial_listing_leaves_rollups_null` | >20% nulls gives partial status, null rollups and retry |
| `test_fetch_playlist_playlist_end_backcompat` | `fetch_catalog` behaviour unchanged without `playlist_end` |
| `test_quote_validation_drops_hallucinated_quotes` | an unsupported quote removes the field and sets `pending_review` |
| `test_score_missing_components_excluded` | null engagement is not treated as 0; coverage < 1 |
| `test_lane_rules_table` | a parametrised truth table for every lane rule |
| `test_claim_rpc_no_double_lease` (gtm-style) | concurrent claims never return the same row |
| `test_link_gmc_beats_name` / `test_link_ambiguous_stays_suggested` | link precedence and ambiguity handling |
| `test_promote_idempotent` | a second run creates no new rows |
| `test_refresh_cohort_keeps_creator_members` | `segments refresh` (all cohorts) preserves `tiktok_doctor_creators` |
| `test_refresh_outreach_includes_non_cqc_creator_clinics` | a creator clinic without CQC names gets a contact |
| `test_infer_email_source_tiktok_bio` | the new enum value is used |
| MCP `test_creator_tools_paginate` / `test_tiktok_tools_never_return_creators` | pagination fields present; `get_tiktok_cohort` rows contain no creator handles |

`scripts/verify-supabase-schema.py` adds all new tables, the RPC, the views and the new GTM columns, and exits non-zero if any are missing.

---

## Expected funnel (estimates; Step 0 replaces them with measurements)

| Stage | Count | Basis |
|---|---|---|
| Discovered | 8–15k | ~60 hashtag seeds × 100–300 authors plus ~1,500 practitioner searches |
| After pre-screen | 5–9k | generic tags carry many non-medical authors |
| Profiled | 5–9k | 1 request each; ~6 s → ~10–15 h spread over nights |
| Screened in | 2.5–3.5k | |
| Hydrated | 2.5–3k | ~30 s each → ~25 h over ~2 weeks of worker bursts |
| Research lane | 1.5–2.2k | |
| UK doctors | 200–500 | UK MedTok is small; practitioner-name seeds dominate this |
| Customer lane | 100–300 | |
| Promoted after review | 50–150 | |

If Step 0 measures profile or listing throughput below 50% of these rates, cap hydrate at 1.5k and prioritise the `uk` and `practitioner` slices.

---

## Tasks

- [ ] 🟥 **Step 0: Spike and gate (no production code)**
  - [ ] 🟥 Create a dedicated research TikTok login. Test `browser_session` on 5 hashtags plus 20 practitioner-name searches: unique authors, captcha rate, requests/hour
  - [ ] 🟥 Price and test one `vendor_api` on the same seeds: yield, cost per 1k authors, whether author follower count and signature are included
  - [ ] 🟥 Profile-fetch 200 known handles: success, block and not-found rates; sustainable requests/hour; blob schema stability across 3 days
  - [ ] 🟥 Flat listing with `--playlist-end 23` on 50 handles: time, null rate, throttle behaviour
  - [ ] 🟥 Write `docs/CREATOR_CORPUS_SPIKE.md` covering the chosen discovery source, measured rates (these replace the rate-limit defaults) and cost
  - [ ] 🟥 **Gate:** a source yields ≥300 unique authors from 20 seeds with <5% blocked, and profile-fetch success ≥90%. Otherwise stop and re-plan

- [ ] 🟥 **Step 1: Schema and store**
  - [ ] 🟥 Write `sql/014_creator_corpus.sql` (tables, RPC, views, RLS) and `sql/015_gtm_creator_handoff.sql`
  - [ ] 🟥 Apply both manually in the Supabase SQL editor; extend and run `scripts/verify-supabase-schema.py`
  - [ ] 🟥 `creators/paths.py`, `store.py` (table allowlist), `runs.py` (counters, exit codes), `ratelimit.py`
  - [ ] 🟥 Register the `creators` channel in `marketing_pipeline/cli.py`; add `creators status` (funnel counts by stage, lane and slice)
  - [ ] 🟥 Isolation tests: allowlist, no-DocMap-tables, no-activate-account, research-profile path, DocMap tree unmodified

- [ ] 🟥 **Step 2: Manual intake, profile fetch, screen**
  - [ ] 🟥 `import-handles`, `seed-import`
  - [ ] 🟥 `profile_fetch.py` with fixture tests; snapshots; cache
  - [ ] 🟥 `bio_parse.py`, `screen.py`, batched LLM micro-screen
  - [ ] 🟥 Acceptance: 200 imported handles all reach a terminal or `screened` state; counters sum to 200; no row left leased past expiry

- [ ] 🟥 **Step 3: Hydrate**
  - [ ] 🟥 Add `playlist_end` to `fetch_playlist` with a back-compat test
  - [ ] 🟥 `hydrate.py` (caption parse, partial/blocked handling) and `rollups.py`
  - [ ] 🟥 Acceptance: posts_30d spot-checked by hand against 10 live profiles; a partial listing leaves rollups null

- [ ] 🟥 **Step 4: Classify, score, eval**
  - [ ] 🟥 `classify_v1` prompt, pydantic schema, quote validation, input-hash cache
  - [ ] 🟥 `score.py` with the lane truth-table tests; `creators score --all`
  - [ ] 🟥 Hand-label `labels_v1.csv` (150 profiles); `creators eval`
  - [ ] 🟥 **Gate:** eval thresholds met before Step 6 promotion is enabled

- [ ] 🟥 **Step 5: Discovery at volume**
  - [ ] 🟥 Implement the adapter chosen in Step 0 (`browser_session` and/or `vendor_api`) behind `DiscoverySource`
  - [ ] 🟥 `seed-practitioners` via `gtm_pipeline creators export-practitioner-seeds` (reads `integrated_practitioners`, **not** `…_with_phin`)
  - [ ] 🟥 Starter seed CSVs (global, uk, creator-behaviour); slice budget enforcement; seed yield backfill after scoring
  - [ ] 🟥 `drain` command (profile → screen → hydrate → classify → score with budgets and deadline)
  - [ ] 🟥 Acceptance: the first cycle reaches ≥2k scored profiles; every seed shows `doctor_yield`; no endpoint breaker left tripped at run end

- [ ] 🟥 **Step 6: GTM link, review, promote**
  - [ ] 🟥 `gtm_pipeline/creators/link.py` with the precedence and ambiguity tests; `--recheck` duplicate guard to `gtm_match_reviews`
  - [ ] 🟥 Review CSV export/import
  - [ ] 🟥 `promote.py`; `refresh_cohort` creator builder branch; `infer_email_source` `tiktok_bio`; `refresh_outreach_contacts(cqc_named_only=False)` for the cohort
  - [ ] 🟥 Governance sign-off note in `docs/`
  - [ ] 🟥 Acceptance: 20 confirmed customers promote idempotently; `gtm-pipeline contacts list --status ready` shows them with a populated evidence angle; `segments refresh` keeps them

- [ ] 🟥 **Step 7: MCP and exports**
  - [ ] 🟥 `tools/creator_corpus.py` plus registrations, instructions section, `/health` field
  - [ ] 🟥 `creators export` and the generated data dictionary
  - [ ] 🟥 Tests: pagination; `get_tiktok_*` returns no creator rows; review requires `confirmed=true`
  - [ ] 🟥 Acceptance: one Claude session goes summary → `list_creators(lane=research, specialty_key=dermatology)` → `get_creator_profile` → cited comparison, with no manual SQL

- [ ] 🟥 **Step 8: Graph expansion**
  - [ ] 🟥 `discovery/graph.py` from mentions and stitch/duet targets of the top 100 per lane; depth 1 per cycle
  - [ ] 🟥 Acceptance: new handles flow through Steps 2–6 and graph seeds report their own `doctor_yield`

- [ ] 🟥 **Step 9: Schedule and refresh**
  - [ ] 🟥 `creator_corpus_drain` and `creator_corpus_refresh` jobs (default off), deadline before the DocMap TikTok window, data-dir assertion
  - [ ] 🟥 `creators purge` for discard retention
  - [ ] 🟥 Acceptance: 7 consecutive nights with no DocMap TikTok job failure attributable to throttling; snapshots accrue for customer and research lanes

- [ ] 🟥 **Step 10: Deep peer (handful only)**
  - [ ] 🟥 `creators promote-peer` wrapper plus `peer_account_handle` write-back
  - [ ] 🟥 Acceptance: one promoted account passes the existing peer release gate unchanged

---

## End-to-end acceptance

**It works:**
- [ ] A clean-slate run of 200 imported handles plus one discovery cycle: `creators status` counts reconcile exactly (discovered = excluded + unavailable + in-flight + scored), and every run row has counters and a terminal status
- [ ] Re-running any command is idempotent: no duplicate profiles, videos, snapshots on the same timestamp, links or GTM rows
- [ ] A throttled or blocked run never overwrites profile facts, videos or rollups with empty values, and exits non-zero

**It integrates:**
- [ ] `python scripts/verify-supabase-schema.py` exits 0 with the new tables, RPC, views and GTM columns
- [ ] Promoted customers appear in `gtm-pipeline contacts list --status ready` and in `list_ready_for_sales()`, and can be enriched with the existing `rocketreach`/`linkedin-find --cohort tiktok_doctor_creators`
- [ ] `gtm-pipeline segments refresh` (all cohorts) leaves `tiktok_doctor_creators` membership intact
- [ ] The MCP exposes the six creator tools; `get_tiktok_cohort()` still returns `account=docmap` and `catalog_size=187`; `content_posts` and `document_embeddings` row counts are unchanged from before the corpus
- [ ] One research account promoted through `promote-peer` passes the existing peer release gate

**The data is immediately useful and organised:**
- [ ] `creator_corpus_current` has one row per scored account with the v1 output columns: handle, specialty, followers, posts/30d, median views, private practice, growth intent, lane, score, plus coverage and review state
- [ ] Every lane and score can be explained from `lane_reasons` and `score_breakdown` alone; every assessment claim is backed by a validated verbatim quote
- [ ] The customer queue is ordered by `customer_score`, carries a best link and a sales-angle evidence blob, and excludes `do_not_contact` and DNC practitioners
- [ ] The research board is ordered by `research_score` within specialty, with band-relative reach so large accounts do not crowd out mid-size ones
- [ ] CSV exports open with a generated data dictionary; seed yields show which searches to keep
- [ ] Eval thresholds are met and recorded for the classifier version in use

---

## Decisions needed from the owner

1. **Discovery source after Step 0:** a research TikTok login driven by Playwright (free, local, fragile), a vendor API (paid, worker-safe), or both.
2. **Specialty tiers** for `customer_score` commercial fit. Default is the `sql/011` priority keys as tier A and dermatology as tier B.
3. **Legitimate-interest sign-off** for storing and contacting UK doctors from public TikTok bios.
4. **Whether promotion should also create `clinic_accounts`** (the web CRM). v1 stops at GTM contacts because `clinic_accounts.website_url` is NOT NULL and `clinic_sources.type` has no social source.

## Out of scope (v1)

- Instagram, YouTube or LinkedIn fetching (handles are recorded only)
- Comments, commenter graphs, following lists
- Embeddings or `search_knowledge` over the corpus
- Web UI for the corpus (MCP and CSV only)
- Automatic outreach drafting or sending
- Fixing `SUPABASE_PRACTITIONERS_TABLE` for `search_practitioners` (tracked separately; linking reads `integrated_practitioners` directly)
