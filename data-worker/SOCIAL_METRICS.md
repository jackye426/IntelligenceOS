# Social metric persistence
Daily and weekly account refreshes persist collected numeric counts for the two
TikTok accounts and (unless SKIP_INSTAGRAM is set) the two Instagram accounts
before legacy analysis can contact OpenRouter. A 401 is reported independently.
No fallback to an older JSON dump counts as fresh. Null counters are omitted;
real zeroes are retained. TikTok keeps yt-dlp; existing separately configured
Display API snapshots were not turned on or repurposed by this change.

Apply SQL 017 before enabling this worker version. Consumers must read the
latest observed snapshot by platform/post/source, ordered by captured_at, for
fresh values. Legacy content_posts.metrics is a compatibility cache and can
legitimately differ. The existing MCP reader is a separate repository and is
not changed here. No backend/read-side rollout is implied by this patch.

Instagram uses public Instaloader requests. If Instagram restricts those
responses, configure an already authorized session mount and its username via
SOCIAL_INSTAGRAM_SESSION_FILE and SOCIAL_INSTAGRAM_SESSION_USER; never commit
a session file. Missing fields, IDs or failed retrieval don't update freshness.

Run: cd data-worker && python -m unittest discover -s tests -v


## Public peer tracking
The 09:00 UTC job uses only yt-dlp public video counts for
@robotic.endosurgeon and @drleewarren, at most 80 videos each. No account login,
private analytics, comments retrieval, direct interaction or embeddings.
Peer observations are scoped to their exact handles in
`latest_public_tiktok_peer_metrics` and excluded from the owned view.
Existing distinct peer catalogues and the old creator corpus cron are unchanged.

After applying the migration and verifying the exact worker deploy, an
authorized shell in that worker can run `python main.py --public-peer-metrics-once`.
Choose a time away from the scheduled jobs; a process-local lock does not
coordinate a separate shell invocation. Exit 0 means both peers reported at
least one successful persisted observation and no batch errors; verify the
new stored timestamps, not just that command output. Do not add a permanent
RUN_ON_START or service setting to mimic one run.
