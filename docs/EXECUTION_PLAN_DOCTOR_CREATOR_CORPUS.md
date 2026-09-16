# Feature Implementation Plan — Doctor-creator corpus (TikTok)

**Overall Progress:** `0%`
**Revised:** 2026-09-16 (v4.1 — locks “analyze like Lee Warren”; same ops bar as v4)
**Owner packages:** `marketing-pipeline` (collect + insight cards), `gtm-pipeline` (link + promote into existing sales), `mcp-server` (layered read), `data-worker` (DocMap cron only), **`creator-deep-worker`** (new Railway service)

## TLDR

Build a separate, resumable pipeline that discovers a few thousand TikTok doctor-creators and feeds **organised intelligence** to Claude and to sales. Two products, one store:

- **Research / marketing OS:** every hydrated doctor gets a structured **insight card** and specialty boards so Claude can reason about thousands without loading thousands of libraries. **Any** scored creator can be deep-dived **one at a time** in MCP. In the background, a dedicated worker fleet runs the same Warren pipeline (catalog → stratified sample → Whisper/OCR/components → sync → **auto-written transfer brief**) for every **good-fit** creator, not a handful.
- **Customer / sales:** UK private-practice doctors who want to grow are promoted into the **existing GTM sales path** — `upsert_clinic_intelligence` → `upsert_clinic_people` → `refresh_cohort` → `refresh_outreach_contacts` → RocketReach / LinkedIn-find → `list_ready_for_sales`. No parallel lead list, no new CRM board.

v3 was a correct *analysis* contract and a **prototype ops** contract. It is **not production-grade**. This revision names the production bar and changes L3 from a 40–80 quota to an on-demand + background job system.

---

## Is this production-grade today?

**No.** What we have now (one Warren ingest, APScheduler on a single `data-worker`, session-written briefs, L3 as a quota) is a **working prototype of the method**. Shipping v3 as-is would strand deep analysis in Claude chats and would either starve the fleet or knock out DocMap's own TikTok cron.

A production system is one where:

1. Interactive MCP can deep-dive **any** creator, one library at a time, including one that is still in the queue.
2. Every **good-fit** creator is enqueued automatically; a worker completes the Warren pipeline and writes a **draft brief without a human session**.
3. DocMap's owned TikTok jobs keep their SLO while the fleet runs.
4. Failures are isolated, resumable, observable, and cost-capped.
5. Playbooks cite stored briefs, not live transcript dumps.

### What is already production-*shaped* (keep)

| Piece | Why it counts |
|---|---|
| Fail-closed account scoping on `content_posts` | Warren postmortem; isolation tests |
| GTM durable jobs (`gtm_claim_job_items`, heartbeat, item status) | Real pattern to **copy**, not to reuse as-is |
| Peer sample-plan + `--skip-catalog` resume | A crashed ingest can continue |
| Insight cards + specialty stats | Claude can use thousands without N Warren sessions |
| Counters and non-zero exits on crawl commands | Postmortem lesson #1 |

### What is not production (must add)

| Gap | Why it fails in prod | Bar |
|---|---|---|
| L3 was a quota of 40–80 | Good-fit is ~1.5–2k research-eligible doctors; a quota is a sample of the method, not coverage | Auto-enqueue every good-fit; priority queue |
| Briefs written in a Claude chat | 2,000 sessions do not happen; playbooks stay empty | Background `write_brief` job using the same Python functions as `get_peer_*` |
| One `data-worker` APScheduler | DocMap cron at 03:30 shares TikTok IP; `activate_account` is **process-global** so two peer ingests in one process corrupt paths | Separate `creator-deep-worker`; **one ingest per process**; listing concurrency = 1 globally |
| GTM job stale = 600 s | Whisper of ~200 clips is hours; reclaiming at 10 min double-runs media | `creator_deep_jobs` with heartbeat 60 s and stale **4 h** |
| Isolation audit loads full DocMap on every brief | Fine at 187 rows; must never scan all peer accounts | Keep current peer-vs-DocMap-only audit; add SQL `count` by `account_handle` |
| Media left on disk | Warren sample is GBs; ×1,500 fills a volume | Delete media after Whisper+OCR; persist transcripts + cards only |
| Peer embeddings | `owner_scope` poison if left on | Deep ingest `--skip-embed`; `search_knowledge` stays DocMap |
| No cost/throughput cap | 1,500 × (6–15 h CPU Whisper + ~400 OCR calls) is unbounded spend | Daily budget, measured throughput, skip OCR on auto if over budget |
| No coverage gate before a brief | 51% transcript yield silently produced a “complete” Warren-like run once | Brief job refuses to write unless sample transcript yield ≥ 70% and components ≥ 70% |
| Manual SQL migrations | Drift between env and `verify-supabase-schema.py` | Schema apply is still manual, but worker **refuses to start** if verify fails |
| `SKIP_CREATOR_CORPUS` default true, no alerts | Fleet never runs, or runs and nobody knows it died | Queue depth + success-ratio + DocMap-cron-overlap alerts |
| On-demand not first-class | Human has to wait for quota-select | `request_deep_dive(handle)` jumps the queue; returns `job_id` + ETA |

### Cost math (why a second worker is not optional)

Warren-depth on **one** creator, sampled (~200 videos, not the full catalog):

| Stage | Per creator (order of magnitude) |
|---|---|
| Catalog list (yt-dlp, throttled) | minutes–tens of minutes |
| Download + Whisper `small` CPU, 200 clips | **4–12 hours** on one box (full 1,372 was 15–25 h) |
| OCR on sample | ~400–600 vision calls |
| Components | ~200 LLM calls |
| Auto brief | 1 long-context LLM call over era summary + batched packets assembled in-process |

At 1,500 good-fits × 8 h Whisper ≈ **12,000 CPU-hours**. One Railway replica is ~500 days. Production therefore means: **smaller auto sample (80)**, **priority order**, **optional GPU/faster-whisper**, and **OCR skipped on auto** when the daily vision budget is gone. On-demand deep dives keep the full 200-sample + OCR path.

This is still cheaper than 1,500 interactive Claude rituals, and it is the only way “we analysed them like Warren” is true for the corpus rather than for one neurosurgeon.

---

## Analyze like Lee Warren (locked)

The production bar and the build sequence (Steps 0–10) are in **this** document. The *meaning* of the analysis was locked in `docs/EXECUTION_PLAN_PEER_LIBRARY.md` (2026-09-10) and is reused here as L3. We are **not** copying Warren’s voice, faith frame, or neurosurgery stories. We are reverse-engineering a **clinician-creator operating system** from the posts themselves.

That matches the 11 Sep 2026 DocMap × Simon marketing call: Warren is the research engine (opening hooks, transcripts, cadence, topics, performance), then we assign portable mechanics into a doctor’s specialty and iterate on bookings and audience quality — not agency volume and trial-and-error.

### Product (what we hand a human)

One **transfer brief**, four sections, labelled **hypotheses with confidence**, never findings:

1. **Audience engine** — who it is for, positioning line, repeatable formats with examples, cadence over time (not one average), duration mix by era, owned ladder from bio/captions, and an explicit “what we cannot see”.
2. **Why it works** — winners vs matched underperformers against the **rolling local median**: topic, format, duration, opening construction, spoken vs on-screen vs caption hooks, CTA, recurring authority moves. Cite posts **and** counterexamples. Pacing/edit rhythm is out of scope (OCR is opening frames only).
3. **Portable vs him-specific** — transfer table; each portable item has a confidence level and the observation that supports it.
4. **Assignment template** — fill-in fields, not scripts: `[clinician role] + [named promise] + [who it is for]`, two to four weekly series formats, a cadence the customer can sustain, hook *types*, CTA to an **owned** next step. Instantiated in *their* specialty.

Reject the brief if it is a hook leaderboard, recommends copying his topics/faith/book titles, or makes a causal growth claim the data cannot support (no follower time series, no retention, no paid/organic split).

### Evidence (what the pipeline does)

| Layer | Coverage | Stages | Carries |
|---|---|---|---|
| **A — Metadata** | **Entire catalog** (not last-23) | catalog fetch | Section 1: cadence, rising view floor, format eras, caption CTA ladder |
| **B — Deep** | Stratified sample by era × performance (never most-recent-N) | media, Whisper, opening-frame OCR, hook merge, `generic-clinician` components | Section 2 |
| **C — Comments** | Off by default; named video ids only | comment fetch | Optional audience-response follow-up |

Sample sizes: **on-demand = 200** (Warren default). **Auto fleet = 80** (cost; owner can raise it). Both still fetch full catalog metadata. Missing metrics stay null, never zero. Isolation: `--account`, `--skip-embed`, media deleted after extract.

**How it is read:** one account at a time. Isolation brief → era summary → lean manifest pages → deep packets until the sample is in context → write the four sections. Auto `write_brief` does that **in process** after transcript and component yield ≥ 70%. A Claude session may rewrite a draft after re-reading packets. Playbooks cite the stored brief, not a live transcript dump.

The original peer-library lock (“MCP supplies evidence; Claude writes the thesis”) still holds for **interactive** dives. At corpus scale the fleet LLM is allowed to write a **draft**; humans confirm a sample and any brief cited into a customer assignment. Nothing auto-promotes to constitution.

---

## Why Lee Warren does not scale as-is

`get_peer_*` is built for **one** account. The ritual is: isolation brief → era summary → lean manifest pages → 10–25 deep packets until ~200 transcripts are in context → write a four-section transfer brief. Context budget is the binding constraint (lean manifest ~40–70 tokens/row; a deep packet 600–1,200 tokens; captions on a full catalog 275–480k and therefore forbidden by default).

If we promoted thousands of creators into `content_posts` and asked Claude to "look at the corpus":

- Every `get_peer_*` call reloads up to 5,000 rows for **one** handle.
- There is no list of peer libraries, no specialty board, no compare.
- N × 200 deep packets cannot fit in one session. Even N lean catalogs cannot.
- Isolation audits also load all DocMap rows on every brief.
- Storage and Whisper/OCR cost of 2,000 full catalogs is an order of magnitude past the Warren run (262 posts, 244 transcripts, already a full-day ingest).

So: **do not open thousands of libraries in one MCP session.** Feed thousands through boards and stored briefs. `get_peer_*` is the **interactive** deep dive: one account, current session. The **background** fleet writes those libraries and briefs so the session usually starts from a brief that already exists.

---

## Three evidence layers (the analysis contract)

| Layer | Who | What is fetched | What Claude sees | Purpose |
|---|---|---|---|---|
| **L1 Corpus** | every unique author → all that screen in (~2.5–3.5k) | 1 profile HTML GET + yt-dlp ≤23 videos (research-eligible later re-hydrated to ≤50) | summary, specialty board, paginated lean rows | Who exists; who is worth a look |
| **L2 Insight card** | every hydrated **doctor** (~1.5–3k) | 0 extra network; 1 cached LLM extract (classify + insight) | one card per profile; specialty pattern tables; compare ≤8 | **Deep insight at thousands** — hooks, formats, CTAs, cadence, saves, positioning — without Whisper |
| **L3 Deep library** | **every good-fit**, plus **any** handle on demand | catalog + stratified Whisper/OCR/components via a job queue; auto `write_brief` | `request_deep_dive` / queue status; `list_peer_libraries`; `get_peer_*` **one account per session**; stored brief | Warren-depth evidence + durable artefact |

**L2 is how Claude browses thousands. L3 is how we actually understand each good-fit, asynchronously.** Interactive MCP still opens **one** L3 library at a time. The difference from v3 is the worker, not the context window.

**Explicitly not fetched at L1/L2:** media, Whisper, OCR, component cards, comments, following lists, full catalogs, embeddings, Instagram. IG handles in bios are recorded, not followed.

---

## Verified constraints (2026-09-14)

| Probe | Result | Consequence |
|---|---|---|
| `yt-dlp 2026.08.19`, `tiktok:tag` on `/tag/ukdoctor` | `_WORKING = False`; "No working app info is available"; `entries: [null]`, exit 0 | yt-dlp cannot do hashtag discovery. Keyword search was never supported |
| Logged-out headless Chromium on `/tag/ukdoctor` | Slider captcha; `/api/challenge/item_list/` returns 200 with **zero items** | Browser discovery needs a logged-in session or a vendor API |
| `fetch_catalog --flat-playlist` profile metadata | `drleewarren_profile.json` is all nulls; a full single-video fetch returns `channel_follower_count = NA` | Current fetcher yields **no bio and no follower count** |
| Plain `GET https://www.tiktok.com/@handle` (no login) | HTTP 200; `__UNIVERSAL_DATA_FOR_REHYDRATION__` → `webapp.user-detail.userInfo` has `followerCount`, `heartCount`, `videoCount`, `signature`, `bioLink.link`, `verified`, `isOrganization`, `commerceUserInfo`, `ttSeller`, `language`, `createTime`, `privateAccount`, `secUid`, `id` | **One cheap request per profile gets the profile facts** |
| yt-dlp flat listing of a profile | Works: 262-post Warren ingest; throttles for minutes; null entries when throttled | Keep it for recent videos, capped with `--playlist-end` |
| Live Supabase | `integrated_practitioners` **40,876** rows, **22,433 with `gmc_number`**; `gtm_clinic_people` 9,090; `gtm_clinic_intelligence` 1,513; `gtm_outreach_contacts` 734; `clinic_accounts` 1,683; `doctor_outreach` 115 | GMC-backed identity matching is available at scale |
| Live Supabase | `integrated_practitioner_with_phin` **does not exist** (PGRST205) | Linking must target `integrated_practitioners`. MCP `search_practitioners` is probably broken — fix outside this plan |
| `studio_listen.profile_dir()` | `DATA_ROOT/.tiktok_studio_profile` is DocMap's login | **Never** use it for discovery |
| GTM sales today | Doctify/CQC → `gtm_*` → cohort → one PIC contact. Handoff is `list_ready_for_sales()` / `GET /contacts/outreach?ready_sales=true`. **MCP does not read `gtm_*`.** Next.js CRM is `clinic_accounts`, a parallel surface | Creator leads plug into GTM contacts, not a new list and not `/accounts` unless the owner later says so |
| Peer MCP today | Five `get_peer_*` tools, `MAX_BATCH=25`, `MAX_MANIFEST_PAGE=400`, `MAX_CORPUS_ROWS=5000`. No list of libraries, no specialty board, no compare | Corpus MCP is a new module; it must not route through `get_peer_*` |

DDL path: every migration is applied manually in the Supabase SQL editor, then verified by `scripts/verify-supabase-schema.py`.

---

## Critical Decisions

1. **Two lanes, one store.** Every discovered account gets one row in `creator_profiles`. Lane is derived: `customer | research | both | discard | pending_review`.
2. **Thousands get insight cards immediately; good-fits get Warren-depth in the background.** L2 is mandatory for every hydrated doctor. L3 auto-enqueues every good-fit. Interactive MCP may deep-dive **any** creator (jumps the queue).
3. **MCP is layered, never a dump.** Claude starts at specialty aggregates, then a page of cards, then at most eight-way compare, then at most **one** L3 deep dive per session. Prefer the stored brief when it exists.
4. **Transfer briefs are produced by a job, not a chat.** After ingest coverage gates pass, `write_brief` assembles era summary + sample packets **in process** (same functions as `get_peer_*`, no HTTP loopback) and writes `creator_peer_briefs` as `draft`. Humans confirm a sample and any brief cited into a customer assignment. Later sessions read the brief.
5. **Customer rows are promoted into existing GTM, not copied into a parallel lead list.** Promotion calls `upsert_clinic_intelligence` and `upsert_clinic_people`, then the existing cohort / contact / enrich / list path.
6. **Promotion requires human review.** Scoring suggests; a person confirms. No auto-writes into outreach.
7. **The LLM extracts; code decides.** Classifier/insight card returns labelled fields with verbatim quotes. Lane, scores, specialty patterns and good-fit / queue priority are deterministic.
8. **Missing is null, never zero.** Score components with missing inputs are excluded; `score_coverage` records what was used.
9. **Discovery is a pluggable adapter behind a gate.** Manual handle import exists from day one.
10. **Every command writes counters** to `creator_crawl_runs`. A degraded run exits non-zero.
11. **A separate CLI channel with a table allowlist.** `python -m marketing_pipeline creators …` never calls `config.activate_account`, never imports `tiktok.sync`, and refuses writes outside `creator_*` (plus the documented GTM promote path in `gtm-pipeline`).
12. **The follower band (5k–100k) is a customer score component,** never a discovery filter.
13. **Saves are a first-class research signal.** Engagement for ranking uses saves and shares, not likes-only applause. Matches how we already read Simon vs other DocMap contributors.
14. **Last-23 (or last-50) is current packaging, not growth history.** Follower snapshots on a 30-day cycle become the growth signal once two captures exist. MCP instructions must say this.
15. **Sales handoff must show the angle.** Today's `list_ready_for_sales` omits `evidence`. Creator promotion is wasted if sales only sees name + email. Extend the select; do not build a new UI.
16. **One peer ingest per OS process.** `activate_account` is process-global (Warren leak #6). The deep worker forks a subprocess per handle and never runs two `--account` ingests in one interpreter.
17. **“Analyze like Lee Warren” is the locked method above**, not “copy Lee Warren.” L3 runs that method. L2 insight cards are a cheaper browse layer, not a substitute for the brief.

---

## Architecture

```text
             ┌──────────────── DISCOVERY (Step 0-gated adapters) ─────────────────┐
 seeds ──▶   │ browser_session (research login) │ vendor_api │ manual CSV │ graph │ ──▶ creator_discovery_hits
             └────────────────────────────────────────────────────────────────────┘
                                   │ dedup on tiktok_user_id
                                   ▼
 creator_profiles  discovered ─▶ profiled ─▶ screened ─▶ hydrated ─▶ classified ─▶ scored
                                   │            │            │            │             │
                          profile_html GET   rules+bio   yt-dlp ≤23/50  insight card  lane + scores
                                                                            │
                                            ┌───────────────────────────────┼─────────────────────────┐
                                            ▼ L2                    ▼ L3 job queue                 ▼ customer|both (GB)
                                 creator_insight_cards              creator_deep_jobs               gtm-pipeline creators promote
                                 creator_specialty_stats            (ingest → write_brief)               │
                                            │                       on-demand jumps queue                │ existing:
                                            ▼                               │                       │  upsert_clinic_intelligence
                                 MCP corpus tools                           ▼                       │  upsert_clinic_people
                                 (summary, boards, cards,           MCP get_peer_*                  │  refresh_cohort (new branch)
                                  compare, specialty playbook)      one account / session           │  refresh_outreach_contacts
                                                                                                    │    (cqc_named_only=False)
                                                                                                    │  rocketreach / linkedin-find
                                                                                                    │    --cohort tiktok_doctor_creators
                                                                                                    ▼
                                                                                          list_ready_for_sales()
                                                                                          GET /contacts/outreach?ready_sales=true
```

### Where the code lives

| Package | New module | Responsibility | Must not |
|---|---|---|---|
| `marketing-pipeline` | `src/marketing_pipeline/creators/` | seeds, discovery, profile, screen, hydrate, classify/insight card, score, specialty stats, good-fit enqueue, deep-job handlers, export, eval, drain | import `tiktok.sync` except via `promote-peer` **subprocess**; never `activate_account` inside drain; never `shared.embeddings` |
| `gtm-pipeline` | `src/gtm_pipeline/creators/` | link; promote via **existing** upserts; cohort builder branch | invent a second contact table; write `creator_*` except link/promotion columns |
| `mcp-server` | `tools/creator_corpus.py` | L1/L2 read tools + review write + specialty playbook | return creator rows from `get_tiktok_*` or `get_peer_*` |
| `mcp-server` | `tools/peer_library.py` (extend) | `request_deep_dive`, `get_deep_job`, `list_peer_libraries`, brief get/save | load more than one deep library per tool call |
| `mcp-server` | `tools/gtm_sales.py` (thin wrap) | `list_gtm_ready_for_sales`, `get_gtm_contact` calling existing `list_ready_for_sales` / contact fetch | send email; draft outreach to unconfirmed / pending_review |
| `data-worker` | jobs in `main.py` | DocMap TikTok cron **only**; corpus drain stays off the 03:30 window | peer ingest; `activate_account` for non-docmap |
| `creator-deep-worker` | new Railway service, same repo | claim `creator_deep_jobs`; **one peer ingest per process**; `write_brief`; on-demand first | two ingests in one process; listing during DocMap 03:00–04:00 UTC |
| `sql/` | `014_creator_corpus.sql`, `015_gtm_creator_handoff.sql` | schema including `creator_deep_jobs` | alter `content_posts` or `document_embeddings` |

Local disk is a **cache**: `MARKETING_CREATORS_DATA_DIR`, default `marketing-pipeline/creators/data/`, gitignored. Paths resolve **per call**. A test asserts they differ from `studio_listen.profile_dir()` and `config.DOCMAP_DATA_ROOT`.

---

## Load tiers

| Tier | Applies to | Network | Data | Stored in |
|---|---|---|---|---|
| **0 Discovered** | every unique author | 0 extra | handle, tiktok_user_id, nickname, signature, follower count if present, hit video id, seed | `creator_discovery_hits`, `creator_profiles(stage=discovered)` |
| **Pre-screen** | Tier 0 from generic seeds | 0 | drop only when nickname **and** signature carry no medical signal. Practitioner-name and manual seeds always pass | `stage=excluded, excluded_reason=no_medical_signal_prescreen` |
| **1 Profiled** | pass pre-screen | 1 HTML GET | all `userInfo` fields | `creator_profiles` + `creator_profile_snapshots` |
| **Screen** | all profiled | 0 (batched LLM only for ambiguous bios) | doctor/brand/student signals; bio emails, links, handles, geo, GMC | `screen_*`, `bio_*` |
| **2 Hydrated** | screened-in, cap 2–3k/cycle, highest seed priority first | 1 yt-dlp listing `--playlist-end 23`; research-eligible later `--playlist-end 50` | latest N videos: posted_at, duration, views, likes, comments, shares, **saves**, caption, **caption_hook**, hashtags, mentions, stitch/duet | `creator_videos` + rollups |
| **2b Insight card** | all hydrated with `is_doctor` likely or ambiguous | 1 LLM call (cached on input hash) | doctor/role/specialty/geo/setting/intent **and** positioning, hook jobs, format mix, CTA mix, series markers, caption hooks with quotes | `creator_insight_cards`, denormalised onto profile |
| **Scored** | all with a card or a discard | 0 | lane, customer_score, research_score, breakdown, coverage | `creator_profiles` |
| **2c Specialty stats** | all scored doctors | 0 | per-`specialty_key` distributions and exemplars | `creator_specialty_stats` |
| **3 Linked** | customer or both with GB geo | 0 (Supabase reads) | matches to practitioners / people / clinics / `doctor_outreach` | `creator_links` |
| **4 Promoted** | human-confirmed customers | 0 + existing enrich jobs | GTM clinic, person, contact, cohort | **existing** GTM tables |
| **5 Deep peer** | every good-fit + any on-demand | `creator_deep_jobs` ingest then `write_brief` | full catalog + stratified Whisper/OCR/components + **stored transfer brief**; media deleted after extract; **no embeddings** | existing peer library + `creator_peer_briefs` |

Pinned videos can appear first in a flat listing. All windows are computed by `posted_at`.

### L3 — on-demand any creator + background fleet for every good-fit

Interactive MCP may open **one** peer library at a time, for **any** handle that has at least a profile row. Background jobs run Warren-depth for every **good-fit** without waiting for a chat.

**Good-fit** (deterministic, versioned `GOOD_FIT_VERSION`):

```text
is_doctor
AND doctor_confidence >= 0.8
AND lane IN (research, both, customer)
AND NOT do_not_contact
AND hydrate_status = complete
AND (
      research_eligible
      OR (customer_eligible AND growth_intent_level >= 2)
    )
```

After each `creators score`, `creators enqueue-deep` inserts a `creator_deep_jobs` item for every good-fit that has no succeeded ingest. Idempotent on `creator_profile_id`.

**Priority** (higher claimed first):

| Priority | Who |
|---|---|
| 100 | `request_deep_dive` (human / MCP, any handle) |
| 80 | UK private / lane `customer\|both` |
| 60 | Priority specialties (below), highest `research_score` first |
| 40 | Remaining research-eligible |
| 20 | Backfill / retry |

Priority specialties (also practitioner seeds; extend `gtm_pipeline.segments.specialty._CANONICAL_PATTERNS`):

`obstetrics_gynaecology, fertility, menopause, endometriosis, ivf, dermatology, colorectal, general_surgery, gastroenterology, urology, general_practice`

**Two ingest qualities:**

| Path | Sample | OCR | Embed | When |
|---|---|---|---|---|
| `auto` | 80, stratified | skip if daily vision budget spent; else opening-frames on sample | never | background good-fit |
| `on_demand` | 200, stratified (Warren default) | yes | never | `request_deep_dive` or `--quality on_demand` |

Both still fetch the **full catalog metadata** (layer A). Expensive stages stay sampled. Comments stay off.

**Job kinds** on `creator_deep_jobs` / `creator_deep_job_items` (copy GTM durable jobs, **do not** reuse `gtm_pipeline_jobs`):

- `deep_ingest` — subprocess `python -m marketing_pipeline tiktok --account HANDLE fetch-catalog && sample-plan && refresh --from-sample-plan --skip-embed && extract-components --schema generic-clinician && sync-supabase --account HANDLE --skip-embed`; then delete media; coverage counters.
- `write_brief` — only if transcript_yield ≥ 0.70 and component_yield ≥ 0.70 on the sample; assemble packets via `peer_library` Python functions; one LLM write to `creator_peer_briefs` status=`draft`.
- Failed coverage → item `failed` with reason, not a fake brief.

**Do not reuse GTM's 600 s stale window.** Whisper items heartbeat every 60 s; `stale_seconds=14400`. GTM reclaim at 10 minutes would double-download mid-job.

**Process isolation:** `config.activate_account` is process-global (Warren leak #6). The deep worker claims **one ingest item**, forks a subprocess, waits, then claims the next. Never two `--account` ingests in one interpreter. Listing uses a global advisory lock so two replicas cannot yt-dlp-list at once. Whisper may run on a second replica only after listing has finished for that item (payload says `catalog_ready`).

**On-demand MCP:** `request_deep_dive_tool(handle, quality=on_demand, confirmed=false)` previews; `confirmed=true` enqueues priority 100 even if the handle is not good-fit (must be `stage` past `profiled`, not `unavailable`). Returns `{job_id, queue_position, eta_hours, existing_brief, ingest_status}`. `get_deep_job_tool(job_id|handle)` is the status poll. When `ingest_status=succeeded`, existing `get_peer_*` works. If a draft brief exists, ritual B starts there unless the human asks to reopen packets.

**DocMap SLO:** `creator-deep-worker` takes a listing pause 02:50–04:15 UTC. Corpus `drain` stays on `data-worker` before 02:45. `SKIP_CREATOR_DEEP` default **true** until schema verify + one golden ingest (Warren already on disk) replays green.

---

## Data model — `sql/014_creator_corpus.sql`

RLS follows `009`: `authenticated` may select, `service_role` may do everything. Every table carries `created_at` and `updated_at`.

### `creator_seeds`

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| slice | text | `global \| uk \| practitioner \| graph \| manual`; 70/20/10 request budget on global/uk/practitioner |
| source_type | text | `hashtag \| keyword \| user_search \| graph_mention \| manual` |
| value | text | tag without `#`, search term, or a name for `user_search` |
| meta | jsonb | `{specialty_key, practitioner_id, gmc_number, from_creator_profile_id}` |
| priority | int | 0–100; hydrate order inherits max seed priority |
| status | text | `active \| exhausted \| blocked \| paused` |
| cursor | jsonb | adapter resume state |
| hits_total, unique_new_authors, doctor_yield, customer_yield | int / numeric | `doctor_yield` backfilled after classification so bad hashtags are pruned |
| last_run_at | timestamptz | |
| unique | (source_type, value) | |

### `creator_discovery_hits`

`id, seed_id, run_id, tiktok_user_id, handle, video_id, author_nickname, author_signature, author_follower_count (nullable), seen_at` — unique `(seed_id, tiktok_user_id)`.

### `creator_profiles` — one row per TikTok account

| Group | Columns |
|---|---|
| Identity | `id, tiktok_user_id unique not null, sec_uid, handle` (lower, indexed), `handle_history, profile_url` |
| Profile facts (latest successful fetch only) | `nickname, bio, bio_link, follower_count, following_count, heart_count, video_count, verified, is_organization, commerce_user, tt_seller, language, private_account, account_created_at, profile_fetched_at` |
| Discovery | `first_seen_at, seed_slices, best_seed_priority, discovery_count` |
| State machine | `stage` (`discovered \| profiled \| screened \| hydrated \| classified \| scored \| excluded \| unavailable`), `work_status` (`ready \| leased \| retry \| blocked`), `attempts, next_attempt_at, lease_owner, lease_expires_at, last_error, excluded_reason` |
| Screen / bio | `screen_result, screen_reasons, bio_emails, bio_links, bio_handles, credential_signals, geo_signals, gmc_number_in_bio` |
| Activity rollups | `recent_window_n, last_post_at, posts_30d, posts_90d, weeks_active_of_last_8, median_views, median_engagement_rate, median_saves_per_1k, median_shares_per_1k, median_duration_sec, views_to_followers_median, hydrate_status, hydrated_at` |
| Current insight (denormalised) | `insight_card_id, is_doctor, doctor_confidence, doctor_role, specialty_raw, specialty_key, geo_country, geo_confidence, practice_setting, growth_intent_level, positioning_line, hook_jobs, format_mix, cta_mix` |
| Scoring | `lane, lane_reasons, customer_score, research_score, score_breakdown, score_coverage, scoring_version, scored_at` |
| Review | `review_status, review_lane_override, reviewed_by, reviewed_at, review_note, do_not_contact` |
| Promotion | `promoted_clinic_intelligence_id, promoted_person_id, promoted_at, peer_account_handle, peer_promoted_at` |
| Deep fleet | `deep_status` (`none \| queued \| ingesting \| ingested \| brief_draft \| brief_failed \| brief_confirmed`), `deep_quality` (`auto \| on_demand`), `deep_job_id`, `good_fit bool`, `good_fit_version` |
| Provenance | `provenance jsonb` |

Indexes: `(stage, work_status, next_attempt_at)`, `(lane, customer_score desc)`, `(lane, specialty_key, research_score desc)`, `(geo_country)`, `(review_status)`, `(deep_status)`, `(good_fit, research_score desc)`.

### `creator_profile_snapshots`

`id, creator_profile_id, captured_at, follower_count, following_count, heart_count, video_count, source`. Insert only on successful fetch. Re-profile every 30 days. `follower_delta_30d` / `follower_delta_90d` are computed at score time once ≥2 snapshots exist — the growth signal the Warren analysis could not have.

### `creator_videos`

`video_id pk, creator_profile_id, url, posted_at, duration_sec, view_count, like_count, comment_count, share_count, save_count (all nullable), caption, caption_hook text, hashtags text[], mentions text[], stitch_or_duet_of, first_seen_at, metrics_updated_at`.

`caption_hook` = first sentence or first 80 characters of caption, whichever is shorter, stripped. Cheap opening-proxy at corpus scale (not OCR). Prune keeps latest 50 per profile, scoped to `creator_profile_id`.

### `creator_insight_cards` — L2, one current card per doctor

This is what "deep insight into thousands" means in the database.

`id, creator_profile_id, classifier_version, prompt_fingerprint, model, input_hash, output jsonb, evidence jsonb [{field, quote, source: bio|nickname|caption:<video_id>}], quote_validation jsonb, is_doctor, doctor_confidence, doctor_role, specialty_raw, specialty_key, geo_country, geo_confidence, practice_setting, growth_intent_level, positioning_line text, named_promise text, who_it_is_for text, hook_jobs text[]` (from a fixed vocab: `name_the_problem, contradict_belief, authority_first, curiosity_gap, numbered_promise, patient_situation, myth, other`), `content_formats text[], format_mix jsonb {format: count}, cta_types text[], series_markers text[], caption_hooks text[]` (up to 8), `created_at` — unique `(creator_profile_id, classifier_version, input_hash)`.

Failed quotes are dropped. If `is_doctor`, `geo_country` or `growth_intent_level` loses all support, those fields go unknown/null and `lane=pending_review`.

### `creator_specialty_stats` — server-side boards

One row per `specialty_key` (plus a `_all` row), rebuilt after each score run. Claude reads this **instead of paging 2,000 cards**.

`specialty_key, n_doctors, n_uk_private, n_deep_libraries, median_followers, p25_followers, p75_followers, median_posts_30d, median_saves_per_1k, median_shares_per_1k, median_views_to_followers, format_histogram jsonb, cta_histogram jsonb, hook_job_histogram jsonb, median_duration_sec, exemplar_handles jsonb {high_saves: [], high_efficiency: [], mid_size: [], uk_private: [], contrast_vanity: []}, rebuilt_at`.

Exemplars are handles only (≤5 per bucket). Full cards are loaded with `get_creator_profile` / `compare_creators`.

### `creator_peer_briefs` — stored L3 artefacts

`id, creator_profile_id, account_handle, status` (`draft \| confirmed \| rejected`), `source` (`auto_job \| mcp_session`), `artefact jsonb` (four sections + limits + confidence table), `evidence_video_ids text[], coverage jsonb {transcript_yield, component_yield, sample_n, catalog_n}, model, created_at, confirmed_by, confirmed_at`. Unique current non-rejected row per handle.

`write_brief` is the default author (`auto_job`). An MCP session may overwrite a draft after a human re-reads packets. Playbooks cite `confirmed` first; they may cite `draft` only when labelled as unreviewed.

### `creator_deep_jobs` / `creator_deep_job_items`

Same shape as `gtm_pipeline_jobs` / `gtm_pipeline_job_items` (claim, heartbeat, attempts, result jsonb) with kinds `deep_ingest | write_brief`, `stale_seconds` default 14400, unique `(kind, item_key)` where `item_key` is `creator_profile_id`. Priority integer on the item. RPC `creator_claim_deep_job_items` mirrors `gtm_claim_job_items` but orders by `priority desc, created_at`.

### `creator_links`

`id, creator_profile_id, target_table` (`integrated_practitioners | gtm_clinic_people | gtm_clinic_intelligence | doctor_outreach`), `target_id, method` (`gmc_in_bio | email_exact | bio_domain | name_specialty | name_only | manual`), `confidence, evidence, status` (`suggested | confirmed | rejected`), `reviewed_by, reviewed_at` — unique `(creator_profile_id, target_table, target_id)`.

### `creator_crawl_runs`

`id, command, source, params, status` (`running | completed | degraded | blocked | failed`), `budget, counters, expectations, worker, started_at, finished_at, error`.

### RPC `creator_claim(...)`

Same pattern as `gtm_claim_job_items`: reclaim expired leases; `FOR UPDATE SKIP LOCKED`; `work_status='leased'`.

### Views

- **`creator_corpus_current`** — one lean row per scored profile: handle, url, nickname, specialty_key, doctor_role, geo_country, follower_count, posts_30d, median_views, median_saves_per_1k, median_shares_per_1k, median_engagement_rate, private_practice, growth_intent_level, positioning_line, lane, scores, coverage, review_status, promoted, good_fit, deep_status, last_post_at, scored_at. **No caption dumps. No transcripts.**
- **`creator_customer_queue`** — lane `customer|both`, `do_not_contact=false`, not promoted, `customer_score desc`, best link joined.
- **`creator_research_board`** — lane `research|both`, ordered by `specialty_key, research_score desc`.

---

## Pipeline stages in detail

### Rate limiting, leases, circuit breaker

- Token bucket (Step 0 replaces defaults): `profile_html` 1 / 4–8 s; `listing` 1 / 20–40 s; `browser_discovery` 1 scroll / 3–6 s, ≤40 scrolls per seed.
- Block signals: HTTP 403/429; HTML without the rehydration blob; `statusCode` not in {0, 10202, 10221}; captcha text; listing with >20% null entries.
- Circuit breaker: 5 consecutive blocks pause 30 min; a second trip ends the run `status=blocked` and releases claims to `retry`.
- Budget: `--max-requests` and `--deadline HH:MM`. Worker hard-stops at 02:45 UTC so DocMap's 03:30 TikTok jobs never share a throttled IP.
- Retry: 15 min → 2 h → 24 h → `blocked`.
- Exit codes: `0` completed; `2` degraded; `3` blocked.

### 0. Seeds

- `creators seed-import --file seeds.csv`
- `creators seed-practitioners --specialties obstetrics_gynaecology,fertility,menopause,endometriosis,ivf,dermatology,colorectal,general_surgery,gastroenterology --limit 1500` shells out to `python -m gtm_pipeline creators export-practitioner-seeds` (reads `integrated_practitioners`, **not** `…_with_phin`). `meta` carries `practitioner_id` and `gmc_number`.
- Starter hashtag CSVs: global MedTok; UK (`ukdoctor`, `nhsdoctor`, `gpuk`, `privatedoctoruk`, `harleystreet`, city+specialty); creator-behaviour (`doctorsoftiktok`, `learnontiktok`); **colorectal / bowel / general surgery** tags for the Simon wedge.
- Slice budget `--slice-budget global=0.7,uk=0.2,practitioner=0.1`.

### 1. Discovery

Interface: `DiscoverySource.run(seed, budget) -> Iterator[DiscoveryHit]`.

| Adapter | How | Status |
|---|---|---|
| `manual` | `creators import-handles --file handles.csv --slice manual` | Build first |
| `browser_session` | Playwright persistent context on a **dedicated** research login at `CREATORS_DATA_DIR/.tiktok_research_profile`. Intercept `/api/challenge/item_list/`, `/api/search/user/full/`, `/api/search/general/full/` (same pattern as `studio_listen._attach_response_listener`). Captcha stops that seed | Step 0; local only |
| `vendor_api` | `CREATORS_VENDOR` + `CREATORS_VENDOR_KEY`; cost per call in run counters | Step 0; worker-safe |
| `graph` | No network. Mentions and stitch/duet of the top 100 per lane → `graph_mention` seeds | After first scored cycle |

Dedup on `tiktok_user_id`. Handle changes update `handle_history`. A second seed increments `discovery_count` and never re-queues a profile past `profiled`.

### 2. Profile fetch

`GET https://www.tiktok.com/@{handle}` via `httpx`, desktop UA, `Accept-Language: en-GB`. Parse rehydration → `webapp.user-detail`.

- `statusCode=0` → success, snapshot, gzipped cache, `stage=profiled`.
- `10202` / `10221` → `unavailable`.
- `privateAccount=true` → `unavailable, excluded_reason=private`.
- Missing blob or captcha → **block signal, never "not found"**.
- Failure **must not** overwrite profile facts (postmortem #1).

### 3. Screen and bio parse

Versioned `SCREEN_VERSION`. Exclude brands, `<3` videos, non-medical doctor tokens, students without a qualified signal. Positive MD/consultant/GMC regex; negative dentist/physio/vet/nurse/PhD-without-MD. Ambiguous bios go to a batched micro-screen (50/call). Bio parse: emails, URL class (`own_site | booking_platform | linktree_like | social | other`), IG/YT/X/LinkedIn handles, GMC `\d{7}`, geo weights (`.co.uk` 0.9, GMC/MRCGP/Harley Street 0.8, UK cities 0.6, US board-certified 0.7).

### 4. Hydrate

Extend `fetch_catalog.fetch_playlist` with `playlist_end: int | None = None`. Existing callers unchanged.

- Parse hashtags, mentions, `#stitch with @x` / `#duet with @x`.
- Set `caption_hook` from caption.
- >20% null entries → `hydrate_status=partial`, upsert parsed videos, **rollups stay null**, `retry`. All-null → block, no writes.
- Rollups by `posted_at`: `posts_30d`, `posts_90d`, `last_post_at`, `weeks_active_of_last_8`, `median_views`, `median_engagement_rate = median((likes+comments+shares)/views)` (kept as a diagnostic), **`median_saves_per_1k`**, **`median_shares_per_1k`**, `median_duration_sec`, `views_to_followers_median`, `recent_window_n`. Nulls excluded from medians.
- If 23 videos do not cover 90 days, `posts_90d` is a floor and flagged in `lane_reasons`.
- Second pass: `creators hydrate --research-eligible --playlist-end 50` after first score, so L2 format/CTA mix is not three weeks of a daily poster.

### 5. Classify + insight card

One LLM call produces both identity fields and the marketing card. Model `MODEL_CREATOR_CLASSIFY` (default `config.MODEL_COMPONENTS`) via `shared.openrouter_client.chat_completion`. `max_tokens` 2000.

**Input:** nickname, bio, bio-link class, screen/geo signals, rollups, up to N captions truncated to 300 chars each prefixed `[video_id]`, plus each `caption_hook`.

**Output** (pydantic, `extra=forbid`): identity fields as in v2, plus `positioning_line`, `named_promise`, `who_it_is_for`, `hook_jobs`, `content_formats`, `cta_types`, `series_markers`, `evidence[]`.

Growth intent: 0 none; 1 brand-building; 2 practice promotion (own site / booking platform / "private practice"); 3 explicit book/DM/enquiry CTA.

`specialty_key` via `creators/specialty_keys.json` generated by `gtm_pipeline creators export-specialty-map` so GTM and corpus share one vocabulary (including the new colorectal / surgery keys).

Cache on `(classifier_version, input_hash)`.

### 6. Score, lane, specialty stats

`creators score --all` — no network, no LLM. Then `creators rebuild-specialty-stats`.

**Lane rules** (unchanged logic, still deterministic):

1. excluded/unavailable / not-doctor / `doctor_confidence < 0.6` → `discard`
2. `active` = `posts_90d >= 3 AND last_post_at >= now()-120d`
3. `research_eligible` = `active AND follower_count >= 1000`
4. `customer_eligible` = GB + `geo_confidence >= 0.7` + private/mixed + `video_count >= 3` + not DNC. Inactive UK private **is** eligible (low output + growth intent is a sales angle)
5. lane `both | customer | research | discard`
6. `pending_review` when doctor 0.6–0.8 or customer geo 0.5–0.7
7. `review_lane_override` wins when confirmed

**customer_score (0–100)** — null components excluded; `score_coverage` = weight used / 100:

| Component | Weight | Rule |
|---|---|---|
| Growth intent | 30 | 0/1/2/3 → 0/10/20/30 |
| Commercial fit | 25 | tier A (`obstetrics_gynaecology, fertility, menopause, endometriosis, ivf`) 15; tier B (`dermatology, colorectal, general_surgery, gastroenterology`) 10; other 5; plus private 10 / mixed 6 |
| Audience band | 15 | 5k–100k → 15; 2k–5k or 100k–250k → 8; else 3 |
| Intent engagement | 15 | `median_saves_per_1k` ≥15 → 15; 8–15 → 10; 3–8 → 5; else 0; null if <5 videos with views **and** saves |
| Contactability | 15 | email 15; own site or booking link 8; IG/LinkedIn only 4; none 0 |

**research_score (0–100):**

| Component | Weight | Rule |
|---|---|---|
| Cadence | 20 | `posts_30d` ≥12 → 20; 6–11 → 14; 3–5 → 8; 1–2 → 3 |
| Reach efficiency | 25 | percentile of `views_to_followers_median` **within follower band** × 25; null if band n < 30 |
| Save intent | 20 | percentile of `median_saves_per_1k` within band × 20 |
| Consistency | 10 | `weeks_active_of_last_8` / 8 × 10 |
| Format signal | 15 | a `content_formats` value in ≥3 captions → 15; series marker → 10 |
| Funnel signal | 10 | owned next step (`newsletter, podcast_or_book, course, book_consult`) 10; `link_in_bio` 5 |

Once ≥2 snapshots exist, a **growth** component (weight taken from reach efficiency, documented in `SCORING_VERSION`) uses `follower_delta_90d`. Until then that component is null, not zero.

`score_breakdown` stores input, points, rule id.

### 7. Link — existing identity indexes, new writer

`python -m gtm_pipeline creators link [--lane customer,both] [--dry-run]`. GB only.

Indexes (paged 1,000): `integrated_practitioners` by GMC, email, `person_name_key`, website domain; `gtm_clinic_people` by name/email; `gtm_clinic_intelligence` by domain; `doctor_outreach` by `practitioner_id`.

| Method | Confidence | Default status |
|---|---|---|
| `gmc_in_bio` | 0.99 | confirmed |
| `email_exact` | 0.95 | confirmed |
| `bio_domain` | 0.90 | suggested |
| `name_specialty` | 0.75 | suggested |
| `name_only` | 0.50 | suggested; never used by promotion unless confirmed |

Ambiguous top-confidence matches all stay `suggested`. `doctor_outreach.status='dnc'` sets `do_not_contact`; `converted` is recorded in `lane_reasons`.

### 8. Review

- MCP `review_creator_tool(..., confirmed=false)` — preview unless confirmed (same pattern as `draft_outreach_email`).
- CSV round-trip: `creators review-export` / `review-import`.

### 9. Promote to GTM — plug into the sales path that already exists

Sales today is:

```text
Doctify/CQC extract
  → gtm_pipeline.sync.clinic_intelligence.upsert_clinic_intelligence
  → upsert_clinic_people
  → segments.refresh_cohort / refresh_all_cohorts
  → contacts.outreach.refresh_outreach_contacts   # default cqc_named_only=True
  → rocketreach.enrich.rocketreach_enrich_contacts
  → linkedin.find.linkedin_find_for_contacts
  → contacts.outreach.list_ready_for_sales
  → Railway GET /contacts/outreach?ready_sales=true
```

Creator promotion **calls those functions**. It does not add a lead table, a web board, or a send path.

`python -m gtm_pipeline creators promote [--handle X | --all-confirmed] [--dry-run]` is idempotent. For each `review_status=confirmed`, lane `customer|both`, not DNC:

1. **Clinic** via `upsert_clinic_intelligence`:
   - confirmed link to `gtm_clinic_intelligence` → that id
   - else confirmed practitioner whose website domain matches a clinic
   - else lookup `source_creator_profile_id`
   - else insert: `clinic_name` from bio/site or `"{Dr name} — private practice"`; `website_url` = own-site `bio_link` (booking links go to evidence); `visible_clinic_size='solo'`; `specialties=[specialty_key]`; `evidence=[evidence_item(kind='tiktok_profile', ...)]`; `provenance=make_provenance(source='creator_corpus', lane='tiktok_creator', source_url=profile_url)`; `source_creator_profile_id`
2. **Person** via `upsert_clinic_people` (or a thin wrapper that currently doesn't accept `social_profiles` — add the column first): confirmed people link, or name match inside the clinic, or insert `{full_name, role: founder if we created the solo clinic else specialist, specialty, email, priority: round(customer_score), social_profiles, creator_profile_id, evidence, provenance}`. On an existing person, only fill `social_profiles` / `creator_profile_id` / empty email.
3. Write back `promoted_*` on the profile.
4. `segments.refresh_cohort('tiktok_doctor_creators')` — **must** use the new `rules.source == 'creator_corpus'` branch. Today's `refresh_cohort` scans all clinics by size/specialty and **delete-rebuilds**; without the branch it would empty this cohort or never match solo creator clinics.
5. `refresh_outreach_contacts(cohort='tiktok_doctor_creators', cqc_named_only=False)`. Default `True` skips every creator clinic without a CQC NI/RM. CLI equivalent: `gtm-pipeline contacts refresh-outreach --cohort tiktok_doctor_creators --all-people`.
6. At contact upsert, append a **sales-angle** `evidence_item` (kind `tiktok_creator_angle`) with: handle, profile_url, follower_count, posts_30d, growth_intent_level + quote, specialty_key, positioning_line, top 3 video URLs by views, customer_score, score_breakdown summary, and whether an L3 brief exists.
7. Optional existing enrich: `gtm-pipeline contacts rocketreach --cohort tiktok_doctor_creators` and `contacts linkedin-find --cohort tiktok_doctor_creators`.

**`list_ready_for_sales` change (required, small):** `list_outreach_contacts` currently selects no `evidence`. Add `evidence, provenance` to the select, and join `website_url`, `specialties`, `source_creator_profile_id` with the clinic name. Creator and Doctify contacts then share one handoff JSON. Railway `GET /contacts/outreach?ready_sales=true` inherits it.

**Do not:** create `clinic_accounts` in v1 (`website_url` is NOT NULL; `clinic_sources.type` has no social). Do not add a Next.js `/accounts` card. Do not have MCP send mail. `draft_outreach_email_tool` may be used only after the contact is `ready` and the human confirms — same as today.

**Duplicate-clinic guard:** `creators link --recheck` compares website domains between `source_creator_profile_id` rows and Doctify rows → `gtm_match_reviews` with `dedupe_key = 'creator_clinic:' || creator_profile_id`. Nothing auto-merges.

**MCP sales wrap (thin, after promote works on CLI):**

| Tool | Wraps | Rule |
|---|---|---|
| `list_gtm_ready_for_sales_tool(cohort?, limit≤100)` | `list_ready_for_sales` | include evidence; filter `tiktok_doctor_creators` when asked |
| `get_gtm_contact_tool(clinic_intelligence_id)` | clinic + person + contact + creator angle | no draft |

Instructions: sales-ready means identity + commercial angle + proof + booking path, matching the existing GTM brief. Never draft to `pending_review` or unconfirmed corpus rows. Never use corpus tools as a substitute for `list_ready_for_sales`.

### 10. GTM schema — `sql/015_gtm_creator_handoff.sql`

- `gtm_clinic_intelligence.source_creator_profile_id uuid` unique where not null.
- `gtm_clinic_people.creator_profile_id uuid` (indexed) and `social_profiles jsonb NOT NULL DEFAULT '{}'`.
- Extend `gtm_outreach_contacts.email_source` CHECK with `'tiktok_bio'` (constraint-swap `DO` block from `012`).
- `infer_email_source`: if `person.provenance.source == 'creator_corpus'` and email equals a bio email → `'tiktok_bio'`.
- Seed cohort `tiktok_doctor_creators`: `rules {"source":"creator_corpus","require_people":true}`, priority 85.
- `refresh_cohort` builder branch when `rules.source == 'creator_corpus'`: members = clinics with `source_creator_profile_id` **or** people with `creator_profile_id`.
- Solo creator clinics that also match `solo_og_fertility` etc. **should** appear there too.

Also extend `gtm_pipeline.segments.specialty._CANONICAL_PATTERNS` with:

```text
colorectal: colorectal, bowel surgeon, coloproctolog
general_surgery: general surg
gastroenterology: gastroenterolog, ibd, crohn, colitis
```

Export that map into `creators/specialty_keys.json`.

### 11. MCP — organised for thousands, not for one Warren

Two modules, three rituals. `/health` adds `creator_corpus_surface: "v1"`.

#### L1/L2 — `tools/creator_corpus.py`

All list tools paginate and return `total_rows, returned_rows, next_cursor`. Default page ≤50, hard cap 100. **No tool returns more than 8 full insight cards in one call.**

| Tool | Purpose | Returns |
|---|---|---|
| `get_creator_corpus_summary_tool()` | session start | counts by stage, lane, geo, specialty, review, good_fit, deep_status; queue depth; last 10 run counters; seed yields |
| `get_specialty_board_tool(specialty_key)` | **marketing analysis start** | `creator_specialty_stats` row + exemplar handles only |
| `list_creators_tool(lane, geo?, specialty_key?, min_score?, follower band, review_status?, deep_status?, good_fit?, order=customer_score\|research_score\|saves\|followers\|posts_30d, cursor, limit≤100)` | browse | lean `creator_corpus_current` rows (**no captions, no cards**) |
| `get_creator_profile_tool(handle)` | one creator | profile facts, snapshots, rollups, **full insight card with validated quotes**, latest ≤8 caption_hooks, score breakdown, links, promotion / `deep_status` / queue |
| `compare_creators_tool(handles ≤8)` | side-by-side | rollups, hook_jobs, formats, CTAs, saves/1k, positioning_line, scores — still no transcripts |
| `get_specialty_playbook_tool(specialty_key)` | assign work to a signed doctor | stats + top hook_jobs/formats/CTAs with n and exemplar handles + **cited confirmed L3 briefs** (portable table only) + `not_measurable` block |
| `list_creator_seeds_tool(order=doctor_yield)` | which searches to keep | seed yield table |
| `review_creator_tool(..., confirmed=false)` | human review write | preview or written review |

#### L3 — extend `tools/peer_library.py`

Existing five `get_peer_*` tools **unchanged** (one account, same caps, same isolation audit — peer vs DocMap only, never scan the whole fleet).

| New tool | Purpose |
|---|---|
| `request_deep_dive_tool(handle, quality=on_demand, confirmed=false)` | jump the queue for **any** profiled handle |
| `get_deep_job_tool(handle or job_id)` | ingest/brief status, coverage, ETA |
| `list_peer_libraries_tool(specialty_key?, deep_status?, cursor, limit≤50)` | index only: handle, specialty, catalog_size, sample_n, coverage, brief_status. **No posts.** |
| `get_peer_transfer_brief_tool(account)` | stored artefact or `{found:false, ingest_status, ritual}` |
| `save_peer_transfer_brief_tool(account, artefact, confirmed=false)` | human confirm/overwrite of a draft |

#### Rituals (written into `common/mcp_instructions.py`)

**A. Corpus / marketing a specialty (default when the human asks how doctors in X should post):**

1. `get_creator_corpus_summary`
2. `get_specialty_board(specialty_key)`
3. `list_creators(lane=research, specialty_key, order=research_score)` — one page
4. `compare_creators` on 4–8 exemplars from the board (high saves, mid-size, UK private, contrast)
5. `get_specialty_playbook(specialty_key)`
6. Only if a named handle still needs packets: `get_deep_job` → if ingested, existing peer ritual for **that one account**; if not, `request_deep_dive(confirmed=true)` and wait. Do **not** open `get_peer_content_batch` for a second account in the same session.

Do **not** open `get_peer_content_batch` for a second account in the same session.

**B. One-creator deep dive:** `get_deep_job(handle)`. If a brief exists, read it first. If ingest succeeded and the human wants packets, existing peer ritual, isolation gate first. If ingest is queued, say so and do not pretend L2 captions are transcripts. Last-23/50 on the corpus card is **current packaging**. Growth claims require snapshot deltas or L3 era medians. OCR is opening-frames only. Views are not follower acquisition.

**C. Sales handoff:** `list_gtm_ready_for_sales(cohort=tiktok_doctor_creators)` → `get_gtm_contact`. Draft only via existing `draft_outreach_email` after `confirmed=true`. Corpus `pending_review` is not a lead.

Menu (session open) gains two bullets: specialty creator board / playbook; GTM ready-for-sales with TikTok angle.

### 12. Exports, eval, outcome join

- `creators export --view corpus|customer|research|specialty-stats --format csv` plus generated `docs/CREATOR_CORPUS_DATA_DICTIONARY.md`.
- `creators eval --labels creators/eval/labels_v1.csv` — 150 hand-labelled profiles (~60 UK, ~60 US, ~30 lookalikes). Gate before promotion: `is_doctor` precision ≥ 0.95, GB precision ≥ 0.90, customer-lane precision ≥ 0.85.
- **Outcome join (read-only, no new scrape):** for promoted UK people, `get_gtm_contact` also calls existing `get_appointment_availability(practitioner_name=...)` when a name match exists. Store a **pointer** (`last_availability_check`) on the contact evidence, not a copy of slots. Comment sentiment stays out of v1 (peer comments remain on-demand at L3 only).

### 13. Deep ingest + auto brief (the fleet)

`creators enqueue-deep` after score. `creators promote-peer --handle X --quality auto|on_demand` is the ingest handler, always a **subprocess**. `--skip-embed` is mandatory. Peer release gate in `PEER_INGEST_POSTMORTEM.md` still applies per account. `creators write-brief --handle X` runs coverage gates then the artefact writer.

`creator-deep-worker` (new Railway service): loop claim ingest → subprocess → claim write_brief. Pause listing 02:50–04:15 UTC. `SKIP_CREATOR_DEEP` default true until `scripts/verify-supabase-schema.py` passes and a replay of `@drleewarren` produces a draft brief with yield ≥ 0.70.

`data-worker` must not call promote-peer. Corpus drain remains on data-worker with the 02:45 deadline.

### 14. Workers

- `data-worker` / `creator_corpus_drain`: 01:00 UTC, deadline 02:45, `SKIP_CREATOR_CORPUS` default **true**. Drain = profile → screen → hydrate → classify → score → rebuild-specialty-stats → enqueue-deep → `gtm_pipeline creators link`. No ingest, no promotion.
- `data-worker` / `creator_corpus_refresh`: Sundays 00:30 UTC. Re-profile top 500; re-hydrate top 200; rebuild stats; enqueue newly good-fit.
- `creator-deep-worker`: always-on claim loop (not cron). Ingest + write_brief only.
- Startup: both services run `verify-supabase-schema.py` and exit non-zero if 014/015 missing. `CREATORS_DATA_DIR` and peer data roots asserted outside `DOCMAP_DATA_ROOT`.
- Alerts (logs + `/health` on the deep worker): queue depth, items older than 24 h, success ratio < 0.8 over 50 items, DocMap listing overlap, disk > 70%.

### 15. Data governance

- Public profile data only. Customer lane is identifiable professionals for B2B outreach under legitimate interest — written into `docs/` and signed off before promotion is enabled.
- Retention: `discard` keeps `tiktok_user_id, handle, excluded_reason, first_seen_at`; bio/captions/videos purged after 90 days (`creators purge`).
- `do_not_contact` and `doctor_outreach.status='dnc'` honoured at promotion.
- Research browser login is never DocMap's.

---

## Isolation and integration tests

Keep every v2 isolation test (allowlist, no DocMap tables, no `activate_account`, research profile ≠ studio profile, DocMap tree unmodified, profile-fetch fixtures, partial hydrate, quote validation, missing score components, lane truth table, claim RPC, link precedence, promote idempotent, cohort refresh, `tiktok_bio` email source, MCP pagination, `get_tiktok_*` never returns creator handles).

Add:

| Test | Asserts |
|---|---|
| `test_insight_card_quote_validation` | unsupported quote drops the field |
| `test_caption_hook_is_first_sentence_or_80` | hook never equals a 300-char blob |
| `test_research_score_uses_saves_not_likes_only` | a high-like / zero-save profile does not outrank a high-save peer in-band |
| `test_specialty_stats_exemplars_are_handles_only` | no captions in the stats row |
| `test_good_fit_predicate` | inactive US brand is false; UK private growth_intent 2 is true |
| `test_enqueue_deep_is_idempotent` | second score does not duplicate job items |
| `test_on_demand_outranks_auto` | claim order is priority 100 then 80 |
| `test_write_brief_refuses_low_yield` | 0.51 transcript yield → failed item, no artefact |
| `test_ingest_is_subprocess_not_activate_in_parent` | parent `config.ACCOUNT` stays docmap |
| `test_skip_embed_on_deep_sync` | no `document_embeddings` rows for peer video ids |
| `test_media_deleted_after_ingest` | sample media dir empty; transcripts remain |
| `test_gtm_stale_seconds_not_used` | deep claim uses ≥14400 |
| `test_mcp_compare_rejects_more_than_eight` | |
| `test_mcp_playbook_does_not_inline_transcripts` | |
| `test_list_peer_libraries_has_no_post_payload` | |
| `test_request_deep_dive_requires_confirmed` | |
| `test_isolation_audit_does_not_load_all_peers` | audit queries docmap + one handle only |
| `test_list_ready_for_sales_includes_evidence` | creator angle present after promote |
| `test_refresh_outreach_includes_non_cqc_creator_clinics` | `--all-people` / `cqc_named_only=False` |
| `test_refresh_cohort_creator_source_branch` | generic `segments refresh` keeps `tiktok_doctor_creators` |
| `test_promote_calls_upsert_clinic_intelligence` | mocked; no insert into a non-GTM lead table |

---

## Expected funnel (estimates; Step 0 replaces them)

| Stage | Count | Basis |
|---|---|---|
| Discovered | 8–15k | ~60 hashtag seeds × 100–300 authors plus ~1,500 practitioner searches |
| Profiled | 5–9k | |
| Screened in / hydrated | 2.5–3.5k | |
| Insight cards (doctors) | 1.5–3k | **this is the thousands-scale intelligence** |
| Research lane | 1.5–2.2k | |
| UK doctors | 200–500 | practitioner-name seeds dominate |
| Customer lane | 100–300 | |
| Promoted after review | 50–150 | into **existing** `list_ready_for_sales` |
| Good-fit (L3 auto queue) | ~800–2,000 | research-eligible ∪ (UK private with growth intent ≥2) |
| L3 ingested + draft brief (steady) | same as good-fit, over weeks | fleet throughput, not a quota |
| On-demand deep dives | unbounded | any profiled handle, priority 100 |

If Step 0 measures throughput below 50% of plan, cap hydrate at 1.5k and prioritise `uk` + `practitioner` slices. If Whisper throughput is <4 auto ingests/day, **do not** drop insight cards; shrink auto sample to 40 or pause OCR. Interactive on-demand stays 200-sample.

---

## Tasks

- [ ] 🟥 **Step 0: Spike and gate (no production code)**
  - [ ] 🟥 Dedicated research TikTok login; `browser_session` on 5 hashtags + 20 practitioner-name searches
  - [ ] 🟥 Price one `vendor_api` on the same seeds
  - [ ] 🟥 Profile-fetch 200 known handles (success / block / not-found; blob stability over 3 days)
  - [ ] 🟥 `--playlist-end 23` and `50` on 50 handles: time, null rate, throttle
  - [ ] 🟥 Write `docs/CREATOR_CORPUS_SPIKE.md`
  - [ ] 🟥 **Gate:** ≥300 unique authors from 20 seeds, <5% blocked, profile-fetch success ≥90%. Else stop

- [ ] 🟥 **Step 1: Schema and store**
  - [ ] 🟥 `sql/014` (insight cards, specialty stats, peer briefs, caption_hook, saves, `good_fit`, `deep_status`, `creator_deep_jobs`) and `sql/015`
  - [ ] 🟥 Apply in SQL editor; extend `scripts/verify-supabase-schema.py`
  - [ ] 🟥 `creators/` paths, store allowlist, runs, ratelimit, CLI channel, `creators status`
  - [ ] 🟥 Isolation tests

- [ ] 🟥 **Step 2: Manual intake, profile fetch, screen**
  - [ ] 🟥 `import-handles`, `seed-import`, profile fixtures, bio_parse, screen
  - [ ] 🟥 Acceptance: 200 imported handles reach terminal or `screened`; counters sum to 200

- [ ] 🟥 **Step 3: Hydrate**
  - [ ] 🟥 `playlist_end` + back-compat test; caption_hook; saves/shares rollups; partial listing behaviour
  - [ ] 🟥 Acceptance: posts_30d and saves/1k spot-checked on 10 live profiles

- [ ] 🟥 **Step 4: Insight cards, score, specialty stats, eval**
  - [ ] 🟥 classify_v1 + insight fields, quote validation, cache
  - [ ] 🟥 score.py (saves in research; lane table); `rebuild-specialty-stats`
  - [ ] 🟥 `labels_v1.csv` (150); `creators eval`
  - [ ] 🟥 **Gate:** eval thresholds before Step 6 promotion

- [ ] 🟥 **Step 5: Discovery at volume**
  - [ ] 🟥 Chosen adapter; `seed-practitioners` with colorectal/surgery specialties; slice budget; `drain`
  - [ ] 🟥 Acceptance: ≥2k scored profiles **with insight cards**; every seed has `doctor_yield`; specialty stats n matches scored doctors

- [ ] 🟥 **Step 6: GTM plug-in (existing sales path)**
  - [ ] 🟥 `creators/link.py`; `--recheck` → `gtm_match_reviews`
  - [ ] 🟥 Review CSV
  - [ ] 🟥 `promote.py` calling `upsert_clinic_intelligence` / `upsert_clinic_people`
  - [ ] 🟥 `refresh_cohort` `source=creator_corpus` branch
  - [ ] 🟥 `infer_email_source` `tiktok_bio`; `refresh_outreach_contacts(..., cqc_named_only=False)`
  - [ ] 🟥 `list_outreach_contacts` / `list_ready_for_sales` select `evidence` + clinic website/specialties/source_creator
  - [ ] 🟥 Specialty pattern keys for colorectal / general_surgery / gastroenterology
  - [ ] 🟥 Governance sign-off
  - [ ] 🟥 Acceptance: 20 confirmed customers promote idempotently; `gtm-pipeline contacts list --ready-sales` shows TikTok angle in `evidence`; `segments refresh` keeps them; RocketReach `--cohort tiktok_doctor_creators` accepts them

- [ ] 🟥 **Step 7: MCP corpus + playbook (the thousands feed)**
  - [ ] 🟥 `tools/creator_corpus.py`, instructions rituals A/C, `/health` field, menu bullets
  - [ ] 🟥 Exports + data dictionary
  - [ ] 🟥 Tests: pagination, compare cap 8, playbook has no transcripts, `get_tiktok_*` has no creator handles
  - [ ] 🟥 Acceptance: one Claude session does summary → specialty board → compare 6 → playbook, with no SQL and no `get_peer_*`

- [ ] 🟥 **Step 8: Graph expansion**
  - [ ] 🟥 Mentions/stitch of top 100 per lane, depth 1
  - [ ] 🟥 Acceptance: new handles flow through 2–6; graph seeds report `doctor_yield`

- [ ] 🟥 **Step 9: Schedule, drain, alerts**
  - [ ] 🟥 Drain + Sunday refresh (default off); `creators purge`; verify-schema on boot
  - [ ] 🟥 Acceptance: 7 nights with no DocMap TikTok failure from our throttling; snapshots accrue

- [ ] 🟥 **Step 10: Deep fleet + auto briefs (production L3)**
  - [ ] 🟥 `creator_deep_jobs` + claim RPC (stale 4 h); `enqueue-deep`; good-fit predicate tests
  - [ ] 🟥 `promote-peer` as **subprocess**, `--skip-embed`, media delete; coverage counters
  - [ ] 🟥 `write-brief` coverage gate + artefact writer (in-process `get_peer_*` functions)
  - [ ] 🟥 `creator-deep-worker` service, listing pause 02:50–04:15, `/health` queue metrics
  - [ ] 🟥 `request_deep_dive` / `get_deep_job`; `list_peer_libraries`; playbook cites briefs
  - [ ] 🟥 Replay `@drleewarren` as the golden ingest: yield ≥ 0.70, isolation audit pass, draft brief written **without** a Claude session
  - [ ] 🟥 Thin `list_gtm_ready_for_sales` MCP wrap
  - [ ] 🟥 Acceptance: enqueue 20 good-fits; worker completes ≥3 ingest+brief with DocMap cron green; `request_deep_dive` on a non-queued handle returns priority 100 and is claimed next; a second MCP session loads the draft brief **without** `get_peer_content_batch`; `document_embeddings` has no `peer:*` rows from the fleet

---

## End-to-end acceptance

**It works:**
- [ ] Clean-slate 200 imported handles + one discovery cycle: `creators status` reconciles exactly; every run has counters and a terminal status
- [ ] Re-runs are idempotent
- [ ] A blocked run never overwrites good profile facts/videos/rollups; exits non-zero

**It is organised for MCP at thousands:**
- [ ] `get_specialty_board` returns histograms and exemplar **handles**, not cards
- [ ] `list_creators` pages lean rows; a full card is only on `get_creator_profile` / `compare_creators` (≤8)
- [ ] `get_specialty_playbook` can be consumed in one call and names `not_measurable` (no follower history until snapshots, no bookings unless availability pointer, no spoken hooks unless an L3 brief exists)
- [ ] Opening two L3 libraries in one session is something the instructions forbid and the tools do not encourage (no bulk transcript tool)

**It plugs into existing sales:**
- [ ] Promoted customers appear in `list_ready_for_sales()` with `evidence` containing the TikTok angle
- [ ] `gtm-pipeline contacts rocketreach --cohort tiktok_doctor_creators` and `linkedin-find` work unchanged
- [ ] `segments refresh` (all cohorts) leaves `tiktok_doctor_creators` intact
- [ ] No rows in a parallel lead table; `clinic_accounts` count unchanged unless the owner later opts in

**It isolates:**
- [ ] `scripts/verify-supabase-schema.py` exits 0
- [ ] `get_tiktok_cohort()` still `account=docmap`, `catalog_size=187`
- [ ] `content_posts` / `document_embeddings` DocMap counts unchanged; each ingested peer has `owner_scope=peer:<handle>` and **zero** embedding rows unless a future decision reverses `--skip-embed`

---

## Decisions needed from the owner

1. **Discovery source after Step 0:** research TikTok login (Playwright), vendor API, or both.
2. **Auto sample size and OCR budget.** Default auto = 80 videos, OCR optional; on-demand = 200 + OCR. Changing auto to 200 for everyone is a cost decision, not a product one.
3. **Legitimate-interest sign-off** before M6 promotion.
4. **Whether promotion should also create `clinic_accounts`.** v1 stops at GTM contacts.
5. **Whether MCP should wrap `list_ready_for_sales` in v1** or keep sales CLI/HTTP-only until the evidence select is proven. Default: wrap in Step 10, after CLI handoff is green.
6. **GPU / faster-whisper** if measured CPU throughput is below ~4 auto ingests per replica-day. Do not guess; measure on the Warren replay.

## Out of scope (v1)

- Whisper / OCR / full catalogs at L1/L2 (L3 auto is sampled; on-demand is Warren-sized sample)
- Two peer ingests in one process (`activate_account` is global)
- Reusing `gtm_pipeline_jobs` (600 s stale) for Whisper
- Peer embeddings / `search_knowledge` over creator transcripts
- Instagram, YouTube, LinkedIn fetching (handles recorded only)
- Comments / commenter graphs / following lists at L1/L2
- Web UI for the corpus (MCP + CSV + existing GTM list)
- Automatic outreach drafting or sending
- Auto-merging creator clinics with Doctify clinics
- Fixing `SUPABASE_PRACTITIONERS_TABLE` for `search_practitioners` (tracked separately)
- Loading more than one L3 library into a single MCP batch
