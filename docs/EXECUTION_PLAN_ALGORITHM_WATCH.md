# Execution Plan - Algorithm Watch & Platform Shift Detection

**Created:** 2026-11-26  
**Status:** Plan only - no implementation yet  
**Scope:** X (published ranking code) first; platform shift detection across TikTok, Instagram, LinkedIn and X  
**Primary goal:** Keep content playbooks aligned with how each platform ranks content. Published algorithm changes are treated as hypotheses; our own metrics and our comparables' metrics are the evidence.

---

## TLDR

Three components:

1. **Algorithm watcher (X only).** Weekly check of `xai-org/x-algorithm`. Parse weights, scoring formula and small-account (cold start) rules into a snapshot, diff against the last one, and map each change to the playbook rules it touches.
2. **Change-to-test loop.** Every algorithm-driven change becomes a Gate 2 draft that carries evidence from our data, a proposed A/B test and the metric we expect to move. Nothing is applied without human approval.
3. **Platform shift detector (all platforms).** Use tracked comparables as a control group. If most of them move in the same direction in the same week without changing what they post, flag a platform change and pause attribution of our own results to content.

```text
weekly check -> fetch tracked files -> parse snapshot -> diff -> map to rules -> pull evidence -> Gate 2 draft with test plan -> A/B -> approve / reject
```

---

## Product Decisions

| Decision | Choice |
|---|---|
| Check cadence | Weekly (X says it publishes roughly every four weeks) |
| Autonomy | Suggest only. Gate 2 unchanged: `approve_constitution_amendment(confirmed=true)` is the only write path |
| Conflict rule | Our metrics beat code defaults |
| What the repo tells us | Default values at a pinned commit, not guaranteed live config |
| Baseline | Commit `52d4598` (2026-11-25), see Appendix A |
| Fetch method | GitHub REST API for commit SHA plus raw files. No clone, no build, no execution |
| Shift detection platforms | Every platform where we track a comparable cohort |

### Why the MCP should not adjust strategy on its own

- X notes that published values are defaults, live values come from a config system, and experiments under ~10% of traffic may not appear.
- Weights multiply predicted probabilities, not counts. "One reply = 7 likes" is a misreading that an automated rewrite could bake in.
- Changing the playbook on every release would contaminate our own A/B results, because we could no longer separate our changes from the platform's.

---

## Component 1: Algorithm Watcher (X)

### Tracked files

| Path | What we extract |
|---|---|
| `home-mixer/params/param.rs` | Every `*Weight` param and every cold start param (`ColdStart*`, `LowImpressionsMaxPositionRatio`), with key, type and default |
| `xai-value-model/scoring.rs` | The action terms in `weighted_terms` (which predicted actions are in the formula), plus offset and multiplier functions |
| `xai-value-model/weights.rs` | `reply_weight_for`, `dwell_weight_for` (mutual follow boost logic) |
| `xai-value-model/inputs.rs` | `bidirectional_boost_eligible` (who counts as a mutual) |
| `home-mixer/scorers/author_cold_start.rs` | `cold_start_base_eligible`, the eligibility filter in `apply_cold_start`, `sample_reward` |
| `README.md` | Release dates and release notes |

### Detection

- New APScheduler job in `data-worker/main.py`: `x_algorithm_watch`, weekly (suggest Monday 06:00 UTC), wrapped in `_safe`.
- Call the GitHub commits endpoint for `xai-org/x-algorithm` on `main`. If the SHA equals the last stored snapshot, log and exit.
- If it changed, fetch only the tracked files at that SHA via raw URLs. Treat the content as untrusted text: parse it, never build or run it.

### Parsing

- **Params:** regex over the `param!` macro, multi-line safe, e.g. `param!\(\s*(\w+),\s*([\w:<>]+),\s*"([^"]+)",\s*(.+?)\s*\);` with `re.S`. Capture name, type, key, default.
- **Formula terms:** regex over the `("term", apply(scores.<field>, weights.<field>...))` tuples in `weighted_terms`. Output a set of `(term, score_field, weight_field)`.
- **Logic:** don't try to interpret Rust control flow. Hash the body of each listed function. Any hash change is flagged as `logic_changed` with the diff attached for a human to read.

### Storage (migration `018_platform_algorithm_watch.sql`)

```sql
CREATE TABLE IF NOT EXISTS platform_algorithm_snapshots (
  id BIGSERIAL PRIMARY KEY,
  platform TEXT NOT NULL,              -- 'x'
  source_repo TEXT NOT NULL,           -- 'xai-org/x-algorithm'
  commit_sha TEXT NOT NULL,
  commit_date TIMESTAMPTZ,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  params JSONB NOT NULL DEFAULT '{}'::jsonb,         -- name -> {key, type, default}
  formula_terms JSONB NOT NULL DEFAULT '[]'::jsonb,  -- [{term, score_field, weight_field}]
  logic_hashes JSONB NOT NULL DEFAULT '{}'::jsonb,   -- function -> sha256
  file_shas JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (platform, commit_sha)
);

CREATE TABLE IF NOT EXISTS platform_algorithm_changes (
  id BIGSERIAL PRIMARY KEY,
  platform TEXT NOT NULL,
  from_commit TEXT NOT NULL,
  to_commit TEXT NOT NULL,
  change_type TEXT NOT NULL,   -- weight_changed | term_added | term_removed | param_added | param_removed | logic_changed
  name TEXT NOT NULL,
  old_value JSONB,
  new_value JSONB,
  relative_change NUMERIC,
  affected_rules TEXT[] NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'new',  -- new | drafted | testing | approved | dismissed
  amendment_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Enable RLS on both, matching migration 005.

### What gets flagged

| Change | Flag? |
|---|---|
| Weight change under 10% relative | No, unless the sign flips or it moves to or from zero |
| Weight change of 10% or more | Yes |
| Formula term added or removed | Always |
| Any cold start threshold change | Always (directly affects accounts under the follower cap) |
| Logic hash change | Always, as "needs human read" |
| New param with no rule mapping | Yes, as "new rule candidate" |

### Rule mapping (to Appendix A rules)

| Params / terms | Rules |
|---|---|
| `ReplyWeight`, `BidirectionalFollowReplyWeightBoost`, `bidirectional_boost_eligible` | X1, X2 |
| `ShareViaCopyLinkWeight`, `ShareViaDmWeight`, `ShareWeight` | X3 |
| `MuteAuthorWeight`, `NotInterestedWeight`, `BlockAuthorWeight`, `ReportWeight` | X4 |
| `bookmark` entering `weighted_terms` | X5 |
| `ColdStart*`, cold start eligibility logic | X6, X7 |
| `ClickWeight`, `OpenLinkWeight`, `ProfileClickWeight`, `ContClickDwellTimeWeight` | X8 |
| `FollowAuthorWeight`, anything unmapped | New rule candidate |

---

## Component 2: Change-to-Test Loop

For each flagged change, the MCP drafts a Gate 2 amendment. The rationale must contain:

1. **The change:** old value, new value, commit link.
2. **What it implies,** stated in terms of predicted probability, not counts.
3. **Evidence:** our account's and comparables' metrics on the relevant dimension (e.g. replies per 1k views for X1) over the last 8 weeks, split before and after the commit date.
4. **Proposed test** using the existing A/B tooling (`find_ab_tests`, `record_ab_learning`), with expected metric movement and minimum sample.
5. **Recommendation:** approve now (evidence already supports it), test first (default), or dismiss.

If the code points one way and our data, with adequate sample, points the other, the recommendation is dismiss, and the reason is logged.

### Code changes

- Add `x-algorithm.md` to `ALLOWED_TARGETS` in `mcp-server/tools/constitution_amendments.py`, and handle it in `_section_for_target`.
- Seed `mcp-server/data/playbooks/x-algorithm.md` from Appendix A.

### New MCP tools

| Tool | Purpose |
|---|---|
| `get_algorithm_snapshot_tool(platform, commit=None)` | Current (or historical) weights table, normalised to like = 1, plus cold start thresholds |
| `get_algorithm_changes_tool(platform, since=None, status=None)` | Flagged changes with affected rules |
| `draft_algorithm_amendment_tool(change_id)` | Pull evidence, build the rationale, call `suggest_constitution_amendment` with `target_section="x-algorithm.md"`, set change status to `drafted` |

---

## Component 3: Platform Shift Detector

**Why:** TikTok, Instagram and LinkedIn publish nothing about ranking, and X does not show experiments under ~10% of traffic. Comparables are the only sensor for unpublished changes.

### Method (weekly, per platform)

1. For each tracked comparable, compute trailing 7-day median reach per post and per-1k engagement rates, as a ratio to that account's own trailing 8-week baseline.
2. Compute a weekly content-mix fingerprint per account: format, length, topic cluster, posting frequency. This tells us whether the account changed what it posts.
3. **Flag a shift** when:
   - the cohort has at least 5 accounts with at least 3 posts that week (otherwise report "insufficient cohort"), and
   - at least 60% of them move the same direction beyond threshold (start with median reach ratio below 0.7 or above 1.4), and
   - most of the movers have a stable content-mix fingerprint.
4. If the shift falls within 7 days of a published algorithm change, link it. If not, label it "unpublished change suspected".

Thresholds are starting points; tune after 8 weeks of history.

### Storage

```sql
CREATE TABLE IF NOT EXISTS platform_shift_events (
  id BIGSERIAL PRIMARY KEY,
  platform TEXT NOT NULL,
  week_start DATE NOT NULL,
  metric TEXT NOT NULL,                -- e.g. median_reach, replies_per_1k
  direction TEXT NOT NULL,             -- up | down
  share_of_cohort_moved NUMERIC NOT NULL,
  median_ratio NUMERIC NOT NULL,
  cohort_size INT NOT NULL,
  algorithm_change_id BIGINT REFERENCES platform_algorithm_changes(id),
  label TEXT NOT NULL,                 -- published_change | unpublished_change_suspected
  status TEXT NOT NULL DEFAULT 'open', -- open | explained | dismissed
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Consequences

- Strategy briefs and weekly briefings show open shift events and pending algorithm changes.
- `record_ab_learning` warns when a test window overlaps an open shift event (warn by default, don't block).
- Insights drafted from a flagged window carry a warning label.

New tool: `get_platform_shift_events_tool(platform, since=None, status=None)`.

---

## Dependencies

- **X ingest does not exist yet.** Component 1, and Component 3 for platforms that already have comparables, can ship first. Component 2 for X needs X metrics. X ingest needs its own plan: X API pay-per-use, owned reads for our own account, comparables' timelines (the timeline endpoint returns roughly the 3,200 most recent posts), and a snapshot about 2 hours after each post to capture the cold start window. Reuse `content_metric_snapshots` with `platform='x'`.
- **Shift detection is only as good as the cohort.** Each platform needs fresh comparables data on a regular schedule.

---

## Phases

1. **Watcher:** migration 018, parser, weekly job, seed baseline snapshot from `52d4598`, `get_algorithm_snapshot_tool`, `get_algorithm_changes_tool`, `x-algorithm.md` playbook and `ALLOWED_TARGETS` change.
2. **Shift detector, TikTok first** (the deepest comparable cohort), then other platforms as their cohorts fill.
3. **Change-to-test loop for X,** once X ingest is live.

---

## Tests

- Parser fixture tests against the pinned `52d4598` files; expected values in Appendix A.
- Diff tests with a synthetically edited `param.rs` (weight change, sign flip, new param, removed term).
- Shift detector tests with synthetic cohorts: cohort-wide drop with stable content flags; single-account drop does not; cohort drop with content-mix change is labelled as content, not platform.
- Gate 2 invariant: extend `tests/test_constitution_amendments.py` so no new tool path writes a playbook without `approve_constitution_amendment(confirmed=true)`.

---

## Open Questions

- Does `x-algorithm.md` stay platform-mechanics only, with account-specific strategy (personal account vs DocMap accounts) in separate playbooks?
- Alert channel: weekly brief only, or a push notification for cold start changes and shift events?

---

## Appendix A: Baseline at commit `52d4598` (2026-11-25)

Score = Σ (weight × predicted probability), per viewer. `× like` = weight ÷ 0.708. Read as "per unit of likelihood", not as count equivalences.

| Action | Weight | × like |
|---|---|---|
| Reply from a mutual, on an original post | 5.0 + 15.0 boost = 20.0 | 28.2 |
| Share via copy link | 20.0 | 28.2 |
| Reply | 5.0 | 7.1 |
| Quote | 5.0 | 7.1 |
| Share via DM | 5.0 | 7.1 |
| Follow author | 4.0 | 5.6 |
| Share (other) | 2.118 | 3.0 |
| Repost | 1.0 | 1.4 |
| Like | 0.708 | 1.0 |
| Click into post | 0.274 | 0.39 |
| Open link | 0.2 | 0.28 |
| Photo expand, quoted-post click, dwell (yes/no) | 0.05 | 0.07 |
| Time after clicking in (continuous) | 0.385 | n/a |
| Time in feed (continuous) | 0.0075 | n/a |
| Profile click, video open, video quality view, Grok analyze | 0.0 | 0 |
| Bookmark | not in formula (predicted, used in viewer history) | 0 |
| Not dwelled | -0.02 | -0.03 |
| Block author | -31.2 | -44 |
| Not interested | -53.07 | -75 |
| Mute author | -58.8 | -83 |
| Report | -234.0 | -330 |

Mutual boost applies only to original posts (not replies or reposts) where viewer and author follow each other.

**Cold start (accounts at or under 50,000 followers):** original posts only, at most 2 hours old, under 200 Home impressions. One eligible post per feed load is lifted to roughly the 16th slot, chosen by Thompson sampling on like rate (likes ÷ Home views) with prior Beta(0.75, 49.25), about 1.5%; the top 2 sampled candidates go through and the higher model score wins. Runs with holdout, control and treatment arms.

**Rules**

- **X1.** Write for replies from people in your niche (reply 7x a like; from a mutual on an original post, 28x).
- **X2.** Build mutuals on purpose; the largest positive weight only applies between accounts that follow each other.
- **X3.** Make posts worth sending (copy-link share 28x, DM share 7x).
- **X4.** Irritating a minority is expensive: a 0.1% mute probability costs as much as an 8.3% like rate earns, against a typical like rate of about 1.5%.
- **X5.** Don't optimise bookmarks; they carry no weight in the live formula.
- **X6.** The first 2 hours are an audition for accounts under 50k followers, judged on like rate.
- **X7.** Replies don't get the cold start lift; keep the strongest ideas as original posts.
- **X8.** Clicks earn little; time spent after clicking in counts.

**Not in the code:** no author-reply term (the "75x" figure is from the 2023 release); no link penalty found in scoring weights (not checked elsewhere); author diversity and out-of-network multiplier values not in repo; Grox prompts and some botmaker rules withheld; no production model weights.
