# Peer TikTok evidence: proof before rollout

**Scope:** Simon (@endobowelsurgeon), @drleewarren and @robotic.endosurgeon only. The existing yt-dlp observations are the metric source. This change does not alter daily metric schedules, the refresh implementation, the official API or DocMap-only tools.

## Gate 1: prove the reader

The live domain runs the separate `synaptic-docmap/mcp_social` repository. The read-path work in IntelligenceOS PR #7 is a reference, not a deployment to that service. Adapt and test it against the actual deployed source before releasing. Read by platform + handle + owner scope + video ID; permit these three expected scope pairs, keep DocMap-only tools isolated, and return caption, timed transcript, opening-frame OCR and latest saved public counts with capture time/source. Empty, unavailable, or old evidence must be explicit.

## Gate 2: one public video each

Choose existing known clips with a creator caption, speech and visually legible opening text. Run from the worker environment with its existing backend permissions. The command is preflight-only without `--apply`; add it only after the reader registration/scope check succeeds.

```shell
cd data-worker
python peer_content_proof.py --endobowelsurgeon VIDEO_ID --drleewarren VIDEO_ID --robotic.endosurgeon VIDEO_ID
```

The operator run checks fresh saved metrics and canonical URL, uses bounded temporary downloads and local speech/OCR, writes only the three rows, and confirms DB evidence by rereading it. A duplicate invocation does not re-collect stored proof rows. Then use the authenticated live peer MCP, one account per call, to confirm the same evidence on each exact video ID. This repository's unit tests use fixture DB rows, not a live proof. Keep all scheduled peer enrichment and backfill disabled until this gate succeeds.

## Gate 3: modest enrichment and a separate comments tool

Once Gate 2 passes, cap independently scheduled enrichment by account and by run, start with recent unprocessed clips, skip completed evidence, and check live MCP readback before expanding. Do not piggyback an unbounded enrichment loop onto the current metrics jobs.

Comments are a separate on-demand read for one verified peer video only. Use an already approved public top-level comment source; no replies, account-wide fetch, verbatim archive, indexing, embeddings or theme/sentiment preprocessing. Sort eligible observed comments by like count, with deterministic tie-breaking, and return at most 15 exact/partially redacted comments with like count, observed date if known, source video URL and observed/released sample counts. Do not treat those comments as exhaustive or as a representative sentiment estimate. Drop private health disclosures and any comment that cannot be safely shared after live privacy review; omit usernames and redact identifying details. Use a fail-closed review boundary, not just a keyword list or instructions to Claude after raw contents were sent. Keep the comments tool unavailable if safe review or approved public fetching is unavailable.
