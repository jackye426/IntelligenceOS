"""Retention purge: discard lane keeps identity keys, drops bio/captions/videos after 90 days."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from marketing_pipeline.creators.store import get_store

KEEP_FIELDS = (
    "id",
    "tiktok_user_id",
    "handle",
    "excluded_reason",
    "first_seen_at",
    "stage",
    "lane",
    "do_not_contact",
)

PURGE_PROFILE_FIELDS = (
    "bio",
    "bio_link",
    "bio_emails",
    "bio_links",
    "bio_handles",
    "nickname",
    "positioning_line",
    "hook_jobs",
    "format_mix",
    "cta_mix",
)


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def run_purge(*, older_than_days: int = 90, now: datetime | None = None, store=None) -> dict[str, Any]:
    store = store or get_store()
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=older_than_days)
    profiles = [
        p
        for p in store.list("creator_profiles")
        if p.get("lane") == "discard" or p.get("stage") in {"excluded", "unavailable"}
    ]
    purged = 0
    skipped = 0
    videos_deleted = 0
    for profile in profiles:
        stamped = _parse_ts(profile.get("updated_at") or profile.get("scored_at") or profile.get("first_seen_at"))
        if stamped is None or stamped > cutoff:
            skipped += 1
            continue
        videos = store.list("creator_videos", creator_profile_id=profile["id"])
        for video in videos:
            key = {"video_id": video["video_id"]} if video.get("video_id") else {"id": video.get("id")}
            store.delete("creator_videos", **key)
            videos_deleted += 1
        for card in store.list("creator_insight_cards", creator_profile_id=profile["id"]):
            store.delete("creator_insight_cards", id=card["id"])
        patch = {field: None for field in PURGE_PROFILE_FIELDS}
        patch.update(
            {
                "bio_emails": [],
                "bio_links": [],
                "bio_handles": {},
                "hook_jobs": [],
                "format_mix": {},
                "cta_mix": {},
                "stage": profile.get("stage") if profile.get("stage") in {"excluded", "unavailable"} else "excluded",
                "lane": "discard",
            }
        )
        store.update("creator_profiles", patch, id=profile["id"])
        purged += 1
    return {
        "purged_profiles": purged,
        "skipped_fresh": skipped,
        "videos_deleted": videos_deleted,
        "older_than_days": older_than_days,
        "kept_fields": list(KEEP_FIELDS),
    }
