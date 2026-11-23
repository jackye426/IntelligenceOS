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
