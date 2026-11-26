# X published-ranking watcher

This is for Jack’s personal X content. It watches published code, not Jack’s account, and does not read or act on Simon’s or DocMap’s social accounts.

Run from the repository root on Linux:

```sh
python data-worker/x_algorithm_watch.py run --state-dir /path/to/private/watch-state
python data-worker/x_algorithm_watch.py show --state-dir /path/to/private/watch-state
```

The first run records the pinned November 25 baseline and the current commit if different. Later runs make a single commit request when unchanged. A changed commit fetches the same six allowlisted files by exact SHA, never builds or executes Rust, and writes one atomic snapshot only after validation succeeds. Snapshots contain parameter, scoring-term, logic and file-hash diffs. They are bounded to the most recent 104 observations. If the upstream shape changes, the job fails rather than overwriting the last valid observation. `show` reads the latest observation without networking.

Weekly collection is opt-in. Set `X_ALGORITHM_WATCH_STATE_DIR` to a dedicated, persistent, writable directory on the IntelligenceOS Linux Data-worker to register the Monday 06:00 UTC job. Unset it to keep the job off. Never point it at an ephemeral or committed path. The job logs only counts and source SHA. No Supabase migration, personal metrics ingestion, account enrolment, notifications, Gate 2 draft, or playbook change is included.

Published defaults are not live ranking settings or evidence of a rollout. Weights multiply model predictions rather than counting actions. If the aim is to learn what works for Jack, use matched-age public observations and treat the shortlist as format references until posting cadence and a usable baseline have been verified. Do not use comparator performance to infer that X changed its algorithm.
