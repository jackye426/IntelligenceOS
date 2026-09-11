# Execution Plan — Peer library: audience engine (first subject `@drleewarren`)

**Created:** 2026-09-10  
**Status:** Plan only — not implemented  
**Subject:** [tiktok.com/@drleewarren](https://www.tiktok.com/@drleewarren) (Dr Lee Warren)  
**Depends on:** existing TikTok pipeline (catalog, Whisper, OCR, comments, components) + hosted MCP

---

## TLDR

Ingest `@drleewarren` as an **isolated peer library**. Claude’s job is not “which hooks beat DocMap’s constitution.” It is:

1. How he **created an audience** (positioning, named promise, repeatable format, cadence, off-platform ladder).
2. **Why that engine works** on the evidence we can actually see (videos, captions, CTAs, comments, public stats).
3. What is **portable** so we can assign the same kind of success to **DocMap** and to a **clinic customer we sign** — instantiated in *their* specialty, not copied from his neurosurgery/faith scripts.

Playbook (`content-instruction.md`, `viral-format.md`) is a **later optional check for DocMap’s own page only**. It is not the ranking function and not the sieve for a signed customer.

Instagram is out of scope for v1 (same creative, weaker pipeline).

---

## Goal (locked)

We are studying a **clinician-creator operating system**, not a competitor endo account.

**Success looks like** a transfer brief a human can hand to:

- an internal content assignment for DocMap, and
- a newly signed clinic customer,

…that says: here is the audience engine, here is what to copy as mechanics, here is what is unique to him, here is the assignment template (positioning line, series formats, cadence, hook patterns, CTA to something *we/they own*).

**Failure looks like** a list of his winning hook texts, or a recommendation to post “self-brain surgery” / faith content, or filtering every insight through “ask for operative photos.”

---

## What shifted from the previous draft

| Previous | Now |
|----------|-----|
| Rank his videos, then filter winners through the DocMap endometriosis constitution | Rank his videos vs **his** median only. Constitution does not score him. |
| Borrow = hook types that already match `viral-format.md` | Borrow = **portable engine** (authority, named promise, repeatable format, clip cadence, CTA to owned next step) |
| Primary consumer = DocMap’s TikTok calendar | Primary consumers = **DocMap assignments** *and* **signed-customer content system** |
| Second pass = playbook comparison as the analysis | Second pass = **transfer brief**. DocMap playbook is an optional third pass for *our* page only |
| “Why popular” ≈ outperform vs median | “Why popular” ≈ **positioning + flywheel + packaging**. Median is evidence for packaging, not the whole thesis |

Ingest and isolation (separate data dir, no cron, no mix into DocMap `content_posts` defaults) are **unchanged**.

---

## Subject notes (why this person)

Dr Lee Warren: neurosurgeon, author, podcaster. Promise is named (“Self-Brain Surgery”): neuroscience + faith → rewire thinking. TikTok is likely **top of funnel** into podcast / book / Substack, not a closed content loop.

Topic overlap with DocMap (endometriosis patient-action) is near zero. That is useful: we are forced to extract **mechanics**, not steal themes.

We do **not** have follower history, paid vs organic, or his Studio retention. Do not pretend the pipeline can explain algorithm allocation. Infer audience-building from: bio/promise, repeating series, caption CTAs, comment demand, posting rhythm, authority framing in transcripts.

---

## Claude analysis product (the point of the build)

Claude must produce **one artefact** with four sections. MCP supplies evidence; Claude writes the thesis. Nothing auto-promotes to constitution.

### 1. Audience engine (how he created the audience)

Cite profile + repeating video patterns, not vibes:

- **Who it is for** (inferred from hooks, comments, CTAs)
- **Positioning line** (who he is + named method + promise)
- **Repeatable formats** (talking-head, myth, story, list, …) with examples
- **Cadence** (posts/week, burst vs drip, from `posted_at`)
- **Owned ladder** (what TikTok asks you to do next: follow, podcast, book, newsletter — from captions/CTAs)
- **What we cannot see** (growth curve, traffic mix, retention) — say so

### 2. Why it works (on-platform evidence)

His catalog vs **his** median:

- Winners and underperformers (URLs, views/saves/comments)
- Hook type / funnel / CTA mix (`analyze_components`)
- Spoken vs on-screen vs caption hooks
- Comment questions (generic labels, not DocMap endo regex)
- Authority moves that recur (named credential in first seconds, named method, one claim)

Do not rank him against DocMap videos or against `viral-format.md`.

### 3. Portable vs him-specific

| Portable (assign to DocMap *or* a signed clinic) | Him-specific (do not copy) |
|--------------------------------------------------|----------------------------|
| Clinician authority stated early | Neurosurgery / Iraq / OR stories |
| One **named** method or promise the brand owns | “Self-brain surgery” and faith frame |
| Repeatable series, not one-off explainers | His book/podcast titles |
| Shorts as TOFU into an owned next step | His Substack/podcast URLs |
| Cadence and talking-head packaging | His personal theology |

Portable items become the **assignment template**. Him-specific items are listed so Claude cannot smuggle them into customer work.

### 4. Assignment template (the replicable output)

A fill-in brief, not a content calendar of his topics:

- Positioning line: `[clinician role] + [named promise] + [who it is for]`
- 2–4 series formats to run weekly (with hook-type and structure, not scripts)
- Cadence target (derived from his, then scaled to what the customer can sustain)
- Hook patterns to test (types + first-seconds job, not his wording)
- CTA to **owned** next step (consult, nurse line, booking, brand site) — never his products
- Instantiation notes:
  - **DocMap:** map portable mechanics onto existing patient-action constitution (optional third pass)
  - **Signed customer:** instantiate in *their* specialty and care-journey; do not apply DocMap endo rules as the default

Draft insights go to a **peer store**. `approve_constitution_amendment` is out of band and human-only, and only for DocMap.

---

## Evidence Claude gets (and does not)

**Pass 1 — peer library only**

- Catalog: `posted_at`, caption, transcript, spoken / OCR / caption hooks
- Public stats: views, likes, comments, shares, saves if public
- Components: hook type, funnel, CTA (generic clinician-educator prompt, not DocMap endo)
- Comment questions / objections (generic)
- Derived: cadence, his median, outperform/typical/underperform vs him, hook mix
- Composite **peer brief** (facts, not thesis): cadence, medians, format mix, top/bottom ids, CTA destinations extracted from captions

**Pass 2 — transfer write-up** uses only pass 1 plus the portable/him-specific split. No DocMap constitution in this pass.

**Pass 3 (optional, DocMap-only)** — `get_tiktok_strategy_brief()` after the transfer brief exists, to ask: which portable mechanics already match our constitution, which would need a *DocMap* experiment. Never used for a signed-customer assignment.

**Not provided / not claimed**

- Follower time series, demographics, paid, Studio AWT/finish, Display velocity
- Instagram (v1)
- Full raw comment dumps unless a later LLM comment pass is added
- Bookings or link-click conversion

---

## Isolation (unchanged, non-negotiable)

- Data: `marketing-pipeline/peers/drleewarren/` (or `MARKETING_DATA_DIR` override). Never write `tiktok/data/`.
- No data-worker cron.
- Supabase: `account_handle=drleewarren`, `owner_scope=peer:drleewarren`. All existing MCP reads **default `account=docmap`**.
- No `tiktok_meta/strategy_state` row for the peer. No playbook sync from his run.
- Unique `(platform, platform_post_id)` is fine (TikTok ids are global).

---

## Reuse vs do not reuse

**Reuse:** `fetch_catalog` → download → Whisper → OCR → hook merge → comments fetch → `extract-components` → dataset → cohort / `analyze_components`. Same stages, parameterized account + data root.

**Do not reuse:** Studio, Display API, Business Center; `suggest_hook_repackage`; `suggest_next_tiktok_angles`; decision/constitution tools on peer data; DocMap comment theme regex; DocMap-endo component system prompt; Instagram; mixing libraries in rankings.

---

## Implementation (when we build)

### Pipeline

- `--account drleewarren` on refresh / extract / sync
- Parameterize hardcoded `@docmap` URLs (`fetch_catalog.py`, `download_media.py`, parse/sync URL builders)
- Peer data root; generic component prompt (same hook vocabulary; funnel = awareness / how-it-works / product-CTA)
- Comment labeling: questions + sentiment only
- Stamp `account_handle` + `owner_scope` on sync
- First ingest: cap ~60–80 most recent videos until catalog size is known

### MCP

- `fetch_tiktok_posts(account=...)` default `docmap`
- `get_peer_library_brief(account)` — cadence, medians, hook mix, CTA ladder, top/bottom
- Same `get_tiktok_cohort` / `get_tiktok_video` / `analyze_components` with required `account` when not docmap
- Server instructions: peer ritual = engine → evidence → portable vs specific → assignment template. Do not load DocMap brief until pass 3.

### CLI (target)

```text
python -m marketing_pipeline tiktok refresh --account drleewarren --since 2025-01-01
python -m marketing_pipeline tiktok extract-components --account drleewarren
python -m marketing_pipeline tiktok sync-supabase --account drleewarren
```

---

## Locked decisions

| # | Decision | Choice |
|---|----------|--------|
| 1 | Isolation | Separate data dir + default MCP account filter |
| 2 | Primary analysis | Audience engine + transfer / assignment template |
| 3 | DocMap playbook | Optional pass 3 for DocMap only; never scores the peer; never default for a signed customer |
| 4 | Instagram | Out of v1 |
| 5 | Owned metrics on the peer | Unavailable; say so; do not invent retention |
| 6 | Constitution | Human-only, DocMap-only, after the transfer brief |
| 7 | Customer instantiation | Template is specialty-agnostic; fill with that clinic’s care-journey, not DocMap endo rules |

---

## Out of scope (v1)

- Instagram duplicate ingest
- Automated “post this next week” calendar for DocMap or a customer
- Promoting peer insights into `viral-format.md`
- Scraping his podcast/Substack as a second corpus (captions/CTAs are enough to detect the ladder)
- Multi-peer comparison UI

---

## Acceptance

- [ ] Peer refresh does not touch DocMap `tiktok/data/` or default MCP cohort
- [ ] Claude can load `@drleewarren` cohort + video packets + peer brief
- [ ] A session following the ritual produces the four-section artefact (engine, why it works, portable vs specific, assignment template)
- [ ] Assignment template is fill-in fields, not his scripts
- [ ] Signed-customer path does not require DocMap constitution
- [ ] DocMap pass 3 is optional and clearly labelled

---

## Verification (after first ingest)

- Catalog count and date range for `@drleewarren`
- Whisper / OCR / component coverage on the capped set
- MCP `get_tiktok_cohort(account=docmap)` unchanged
- One dry-run Claude session against the ritual; reject output that is only hook leaderboards or faith-topic recommendations
