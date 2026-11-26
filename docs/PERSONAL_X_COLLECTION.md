# Jack's personal X archive

Separate from DocMap and Simon. Tracks the ten agreed tech-humour and builder accounts using the [TwitterAPI.io timeline endpoint](https://docs.twitterapi.io/api-reference/endpoint/get_user_last_tweets). Public posts and authored quote commentary only; no account login, posting, private posts, third-party replies, or automated strategy changes. Preserve original wording privately for qualitative analysis; don't reproduce it as Jack's copy.

## Rollout, after free credits and access are confirmed

1. Add the provider key as `TWITTERAPI_IO_KEY` in the private worker secret settings, not in chat or Git. No paid plan, top-up, or autorecharge is enabled by the code. Check the provider balance and current rate/call minimum before running.
2. Choose an owner-controlled persistent archive path not available to the public MCP. Try one account first: `python data-worker/personal_x_archive.py backfill --archive /private-volume/personal-x.sqlite --sample`. Verify exact post links and dates before expanding.
3. Remove `--sample` for the one-time ten-account backfill. It looks back 90 days, up to 12 pages (240 returned rows) per account, and records the source cutoff, provider timeline end, or a page cap without treating any as proof of complete history. A completed first account isn't fetched again by backfill.
4. Only after read-back, set `PERSONAL_X_ARCHIVE_PATH` on the IntelligenceOS Data-worker to the same archive. Together with the key this registers daily 17:00 UTC polling. Unseeded accounts are skipped; seeded accounts poll at most three pages for overlap. A missing overlap is marked as a possible gap. The job does not open a port, publish a feed, or alter other jobs.

Snapshot times describe collection, not X refresh. Missing metrics are unknown, not zero. The trial can be stopped by unsetting the archive path. Do not turn the demo's public counts into causal or algorithm claims; compare posts at similar ages and relative to the same author's own baseline.
