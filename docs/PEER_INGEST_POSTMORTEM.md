# Postmortem — first peer library ingest (`@drleewarren`)

**Date:** 2026-09-11
**Scope:** 262-post TikTok ingest into an isolated peer library
**Outcome:** Completed. 262 rows synced, DocMap provably unchanged.
**Defects found:** 8, all silent

---

## The pattern

None of these eight raised an error at the point of failure. Four produced wrong
or missing data behind a zero exit code; two were self-inflicted load that would
have ended in a block; one wrote peer data into DocMap's own directory; one left
correct code undeployed while every local check passed.

Every one surfaced the same way: **a number that should have been moving wasn't,
or a ratio looked wrong.** Not one was caught by an exception, a test, or a log
line. The practical lesson is that a long pipeline run needs counters compared
against expectations at every stage, not just a success exit.

The second pattern is more specific. Five of the eight are the same root cause
wearing different clothes: **DocMap assumptions baked into shared code**, where
the cost is invisible at 70 posts and dominant at 262. The isolation work
targeted data scoping. These lived in filtering, fetching, pathing and pairing.

---

## 1. `null` accepted as a valid playlist

**Where:** `tiktok/stages/fetch_catalog.py`

**Symptom:** `AttributeError: 'NoneType' object has no attribute 'get'`, three
frames from the cause, in a loop over playlist entries.

**Cause:** yt-dlp exits **0** while printing a bare `null` when an extraction
yields nothing. The retry wrapper checked `returncode == 0` and non-empty stdout,
then returned `json.loads("null")`, which is `None`. Original code also passed
`stderr=subprocess.DEVNULL`, so the real reason — throttling — was discarded.

**Why it hid:** exit code 0 plus non-empty stdout looks exactly like success.

**Fix:** judge the payload, not the status. A sentinel distinguishes "nothing
parsed" from "parsed, and the value was null" — both are `None` otherwise, which
is what made the error message wrong on the first attempt at this fix. stderr is
captured and surfaced. Backoff widened to 30s/60s, since TikTok throttles the
listing endpoint for minutes.

```python
payload: Any = _UNPARSED
if proc.stdout.strip():
    payload = json.loads(proc.stdout.decode("utf-8"))
if isinstance(payload, dict) and payload.get("entries"):
    return payload
```

A later variant of the same bug: a throttled listing returns `[None, None, ...]`
as entries. Nulls are now skipped and counted, and an all-null listing **refuses
to overwrite a good catalog with an empty one**.

**Tests:** `test_fetch_playlist_rejects_bare_null`,
`test_fetch_playlist_accepts_partial_json_despite_exit_code`,
`test_fetch_playlist_reports_stderr_on_total_failure`

---

## 2. DocMap's keyword filter discarded good transcripts

**Where:** `tiktok/stages/transcript_utils.py`

**Symptom:** 51% transcript yield. 24 videos with obvious speech produced nothing.

**Cause:** `is_garbage_transcript` discards any transcript under 600 characters
whose *caption* matches a medical keyword list but whose *speech* does not. That
list is DocMap's endometriosis vocabulary, containing generic words like doctor,
surgery, pain and patient. A neurosurgeon's captions trip it constantly; his
speech about rewiring thought does not. Perfectly good talking-head videos were
classified as garbage.

**Why it hid:** rejection is a legitimate outcome of that function, so the drop
looked like "these videos have no speech".

**Fix:** the topic gate is now DocMap-only via `apply_topic_gate`, defaulting to
`not config.is_peer_account()`. Every other rule in the file (empty, too short,
music-only, outro boilerplate) is genuinely generic and still applies to all
accounts.

**Tests:** `test_topic_gate_does_not_discard_peer_transcripts` asserts DocMap
discards the exact transcript the peer keeps; `test_generic_garbage_rules_still_apply_to_peers`
guards against over-correcting.

**Note:** this file was flagged in the plan review before the ingest began, with
a written instruction to check what it gates. It was not acted on. The review
found it; the process didn't close it.

---

## 3. Video-only downloads

**Where:** `tiktok/stages/download_media.py`

**Symptom:** `tuple index out of range` raised deep inside PyAV, via
faster-whisper. Reads as a library bug.

**Cause:** `-f best` ranks by resolution, so on newer TikTok posts it selects the
1080p **HEVC video-only** rendition. The h264 720p rendition is the one carrying
AAC audio. PyAV then fails looking for audio stream 0. 16 files had no audio track
at all.

**Why it hid:** the error names neither audio nor the format selector. Older,
shorter posts have a single muxed format and worked fine, so the failure
correlated with newness and length, which pointed at the wrong suspects.

**Fix:** demand a format carrying both streams, fall back to merging, then to
anything. Every download is verified to contain audio before acceptance, and a
cached video-only file is replaced rather than reused.

```python
"-f", "b[vcodec!=none][acodec!=none]/bv*+ba/b",
```

**Tests:** `test_download_requests_a_format_that_has_audio`,
`test_download_rejects_a_video_only_result`

---

## 4. Re-scraping data already held (three locations)

**Where:** `orchestrator.run_refresh`, `stages/refresh_stats.py`,
`stages/write_master_transcripts.py`

**Symptom:** ~2 hours of metadata requests before any real work; TikTok
throttling; one crash on a throttled listing.

**Cause:** a profile listing already returns views, likes, comments, shares,
saves and duration for every post. Three separate stages re-fetched them one
video at a time:

| Location | Behaviour | Requests at 262 posts |
|---|---|---|
| `run_refresh` | re-lists the profile on every resume | 1 per restart, most throttled endpoint |
| `refresh_stats` | `fetch_yt_meta` per catalog row, ignores the sample plan | ~262 |
| `write_master_transcripts` | `fetch_yt_meta(cache=False)`, forced refresh | ~244 |

The third is the worst: its failure path swallows errors into `{}`, and that same
dict supplies the post timestamp used for sorting. A throttled run would not
crash — it would write blank metrics and **silently destroy the newest-first
ordering** that feeds the dataset.

**Why it hid:** at DocMap's 70 posts this is ~70 fast cached calls. The cost only
becomes structural at scale.

**Fix:** peer runs build metrics from the catalog with no network call
(`use_catalog_only`, `_analytics_from_catalog`). DocMap keeps the live refresh,
because its stats genuinely do go stale. `refresh` gained `--skip-catalog` so
resumes reuse the catalog on disk.

**Tests:** `test_peer_stats_use_the_catalog_not_the_network` (fails loudly if
anything calls yt-dlp), `test_docmap_stats_still_refresh_from_the_network`,
`test_master_transcripts_use_catalog_metrics_for_peers`

---

## 5. O(n²) pairing that also fabricated evidence

**Where:** `tiktok/stages/detect_ab_pairs.py`

**Symptom:** 25 minutes of 100% CPU with no file writes. Looked like a hang.

**Cause:** the auto-suggest block compares every unpaired video against every
other — 29,646 pairs at 244 videos versus 2,415 at DocMap's 70 — and called
`load_whisper_segments(vid_b)` **inside the inner loop**, re-reading and parsing a
transcript JSON from disk on every comparison.

**The worse half:** it produced four A/B pairs asserting *"same underlying audio
with different hook packaging"*. He runs no experiments. That is our inference
about a stranger's content, and it would have entered the analysis as his
behaviour.

**Why it hid:** it eventually completes, so it reads as "slow", and the output is
structurally valid.

**Fix:** skipped entirely for peer accounts, on principle rather than for speed —
A/B machinery is DocMap-only by design. Segment loading is memoised for the
DocMap path. Dataset rebuild went from 25+ minutes to **1.7 seconds**, with zero
pairs.

**Test:** `test_no_auto_ab_pairs_for_peers`

---

## 6. Peer cards written into DocMap's directory

**Where:** `tiktok/stages/video_components_store.py`

**Symptom:** none. Found by checking the output directory rather than the logs.

**Cause:** the store computed its paths as **module-level constants at import
time**:

```python
COMPONENTS_DIR = config.ANALYSIS_DIR / "video_components"   # frozen at import
```

`cli.py` imports the orchestrator, and therefore this module, *before* calling
`activate_account`. So the paths bound to DocMap's tree, and the later rebinding
of `config.ANALYSIS_DIR` never reached them. Every safeguard operated on
`config.ANALYSIS_DIR`; this module had taken a copy.

**Severity:** this is the one that actually breached isolation. One card leaked
into DocMap's tree before it was caught. The shared index had not yet been
rewritten, which is the only reason damage was one file rather than a corrupted
index.

**Fix:** paths resolve per call, so they follow the active account, with a
`__getattr__` shim for callers still reading the old constants. Cards now carry
`account_handle`, `schema_version` and `prompt_fingerprint`, because the leaked
card had **no provenance at all** — on disk it was indistinguishable from
DocMap's own data, which made the leak hard to assess rather than merely hard to
find.

**Knock-on:** the existing component test patched those module constants to
redirect writes. Once they became functions, the test wrote its fixture into the
real DocMap directory — it had been passing by patching the exact thing that made
the bug possible. It now redirects `config.ANALYSIS_DIR`.

**Tests:** `test_component_store_paths_follow_the_active_account`,
`test_component_cards_record_their_provenance`

---

## 7. Empty model responses disguised as JSON parse errors

**Where:** `shared/openrouter_client.py`, `stages/extract_components.py`

**Symptom:** `Expecting value: line 1 column 1 (char 0)` on ~88 of 242 videos
(36%). Plus one `Unterminated string`.

**Cause:** the provider returned empty content under load. The code did
`json.loads("")`, which raises a message describing **our** parsing rather than
**their** empty response. The truncation error was a separate issue: a 2,200
token budget cut long cards mid-string.

**Why it hid:** the error names JSON, so it looks like a schema or prompt problem.
The command still exited 0, and the failures sat in a results list that output
truncation had cut away. Only counting cards against the expected total exposed it.

**Fix:** retry empty responses three times with backoff; if still empty, raise an
error naming the model and the provider's `finish_reason`. Token budget raised to
4,000.

This paid off immediately: the final holdout failed with
`finish_reason='length'`, which correctly identified a model burning its whole
budget without emitting content — on a 406-character transcript, so not a size
problem. Final coverage 243/244.

**Tests:** `test_retries_until_content_arrives`,
`test_persistent_emptiness_raises_a_diagnosable_error`,
`test_first_success_makes_no_extra_calls`

---

## 8. Correctly scoped data behind a stale MCP deployment

**Symptom:** the live MCP exposed no `get_peer_*` tools. Its DocMap cohort and
component tools returned 449 pooled rows, a blended 834-view median, and both
`@docmap` and `@drleewarren` URLs.

**Cause:** the peer pipeline and MCP implementation existed only in the local
working tree. The database migration and peer sync had completed, but the MCP
service was still running the last committed release. Railway therefore served
the old unscoped read code even though the database itself was correctly split.

**Live verification on 2026-09-11:**

- TikTok rows: `docmap=187`, `drleewarren=262`
- Every row's `account_handle`, `owner_scope` and URL handle agree
- Embeddings: `docmap=2229`, no peer embeddings
- Scoped `match_documents` RPC responds successfully

**Fix:** the MCP now reports its peer-surface contract from `/health`, legacy
TikTok outputs identify themselves as `account=docmap`, every scoped database
read validates returned account labels, and `get_peer_library_brief` performs a
cross-library isolation audit before analysis.

**Release gate:** do not trust peer analysis until all are true:

1. `/health` returns `peer_library_surface=v2` and
   `account_scoping=required_fail_closed`.
2. MCP discovery includes all five `get_peer_*` tools.
3. `get_peer_library_brief("drleewarren")` returns
   `isolation_audit.safe_to_analyse=true` and `catalog_size=262`.
4. `get_tiktok_cohort()` returns `account=docmap`, `catalog_size=187`, and no
   `@drleewarren` URL.
5. `python scripts/verify-supabase-schema.py` exits zero.

If the peer tools are absent, Claude must stop. Manually filtering pooled output
by URL is not an acceptable fallback because medians, tiers and component
aggregates have already been contaminated before filtering.

---

## What would have caught these earlier

1. **Assert expected counts between stages.** Every one of these was a counter
   that didn't match. The monitor was eventually extended to track transcript
   yield as a percentage and to assert DocMap's card count stayed at 58 — the
   second of those is what would have caught #6 immediately.
2. **Directory-level checks, not just code-level scoping.** #6 passed every
   scoping test because the test and the code used the same lever. Watching the
   owned tree for unexpected writes is independent of the mechanism.
3. **Never swallow a subprocess's stderr** (#1) and never let a third-party
   failure surface as one of your own error types (#7).
4. **Scale-test shared code before reuse.** #4 and #5 are invisible at 70 posts
   and structural at 262.
5. **Close review findings.** #2 was identified in writing before the ingest and
   left unfixed.

---

## Test coverage

60 tests before this work, **142 after** (87 pipeline, 55 MCP). Every fix above has at least one
regression test, and where a fix risked over-correcting (#2) there is a paired
test guarding the other direction.
