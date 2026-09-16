"""Hydrate recent videos via yt-dlp --playlist-end. Does not call activate_account."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from marketing_pipeline.creators.caption import caption_hook
from marketing_pipeline.creators.paths import normalise_handle
from marketing_pipeline.creators.store import get_store

HASHTAG_RE = re.compile(r"(#\w+)")
MENTION_RE = re.compile(r"@([A-Za-z0-9._]+)")
STITCH_RE = re.compile(r"#stitch with @([A-Za-z0-9._]+)", re.I)
DUET_RE = re.compile(r"#duet with @([A-Za-z0-9._]+)", re.I)

PRUNE_KEEP = 50


def _num(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_entry(entry: dict[str, Any], *, handle: str) -> dict[str, Any] | None:
    vid = str(entry.get("id") or "").strip()
    if not vid or vid == "None":
        return None
    ts = entry.get("timestamp")
    posted_at = None
    if ts:
        posted_at = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    caption = (entry.get("description") or entry.get("title") or "").replace("\r\n", " ").strip()
    stitch = None
    sm = STITCH_RE.search(caption)
    dm = DUET_RE.search(caption)
    if sm:
        stitch = f"stitch:@{sm.group(1).lower()}"
    elif dm:
        stitch = f"duet:@{dm.group(1).lower()}"
    hashtags = [h.lower() for h in HASHTAG_RE.findall(caption)]
    mentions = [m.lower() for m in MENTION_RE.findall(caption) if m.lower() != handle]
    return {
        "video_id": vid,
        "url": f"https://www.tiktok.com/@{handle}/video/{vid}",
        "posted_at": posted_at,
        "duration_sec": _num(entry.get("duration")),
        "view_count": _num(entry.get("view_count")),
        "like_count": _num(entry.get("like_count")),
        "comment_count": _num(entry.get("comment_count")),
        "share_count": _num(entry.get("repost_count") or entry.get("share_count")),
        "save_count": _num(entry.get("save_count")),
        "caption": caption or None,
        "caption_hook": caption_hook(caption),
        "hashtags": hashtags,
        "mentions": mentions,
        "stitch_or_duet_of": stitch,
    }


def _median(values: list[float]) -> float | None:
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return float(median(clean))


def compute_rollups(
    videos: list[dict[str, Any]],
    *,
    follower_count: int | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    dated: list[tuple[datetime, dict[str, Any]]] = []
    for v in videos:
        raw = v.get("posted_at")
        if not raw:
            continue
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dated.append((dt, v))
    dated.sort(key=lambda x: x[0], reverse=True)

    def in_days(n: int) -> list[dict[str, Any]]:
        cutoff = now - timedelta(days=n)
        return [v for dt, v in dated if dt >= cutoff]

    last_30 = in_days(30)
    last_90 = in_days(90)
    last_post = dated[0][0] if dated else None
    week_flags = set()
    for i in range(8):
        start = now - timedelta(days=(i + 1) * 7)
        end = now - timedelta(days=i * 7)
        if any(start <= dt < end for dt, _ in dated):
            week_flags.add(i)

    views = [v.get("view_count") for _, v in dated]
    durations = [v.get("duration_sec") for _, v in dated]
    saves_1k = []
    shares_1k = []
    eng = []
    vtf = []
    for _, v in dated:
        views_n = v.get("view_count")
        if not views_n:
            continue
        if v.get("save_count") is not None:
            saves_1k.append(1000 * float(v["save_count"]) / views_n)
        if v.get("share_count") is not None:
            shares_1k.append(1000 * float(v["share_count"]) / views_n)
        likes = v.get("like_count")
        comments = v.get("comment_count")
        shares = v.get("share_count")
        if likes is not None and comments is not None and shares is not None:
            eng.append((likes + comments + shares) / views_n)
        if follower_count:
            vtf.append(views_n / follower_count)

    ninety_is_floor = len(dated) > 0 and dated[-1][0] > now - timedelta(days=90)

    return {
        "recent_window_n": len(dated),
        "last_post_at": last_post.isoformat() if last_post else None,
        "posts_30d": len(last_30),
        "posts_90d": len(last_90),
        "weeks_active_of_last_8": len(week_flags),
        "median_views": _median([v for v in views if v is not None]),
        "median_engagement_rate": _median(eng),
        "median_saves_per_1k": _median(saves_1k),
        "median_shares_per_1k": _median(shares_1k),
        "median_duration_sec": _median([d for d in durations if d is not None]),
        "views_to_followers_median": _median(vtf),
        "posts_90d_is_floor": ninety_is_floor,
    }


def hydrate_profile(
    profile: dict[str, Any],
    entries: list[Any],
    *,
    store=None,
    prune_keep: int = PRUNE_KEEP,
) -> dict[str, Any]:
    """Upsert parsed videos. Partial listings skip rollups."""
    store = store or get_store()
    handle = normalise_handle(profile["handle"])
    total = len(entries)
    parsed: list[dict[str, Any]] = []
    nulls = 0
    for entry in entries:
        if entry is None:
            nulls += 1
            continue
        row = parse_entry(entry, handle=handle)
        if row is None:
            nulls += 1
            continue
        parsed.append(row)

    if total and nulls == total:
        return {"hydrate_status": "blocked", "null_rate": 1.0, "upserted": 0}

    null_rate = nulls / total if total else 0
    for row in parsed:
        store.upsert(
            "creator_videos",
            {**row, "creator_profile_id": profile["id"]},
            keys=("video_id",),
        )

    videos = store.list("creator_videos", creator_profile_id=profile["id"])
    videos.sort(key=lambda v: v.get("posted_at") or "", reverse=True)
    for extra in videos[prune_keep:]:
        store.delete("creator_videos", video_id=extra["video_id"])
    videos = videos[:prune_keep]

    patch: dict[str, Any] = {}
    if null_rate > 0.20:
        patch.update(
            {
                "hydrate_status": "partial",
                "work_status": "retry",
                "stage": "screened",
            }
        )
    else:
        rollups = compute_rollups(videos, follower_count=profile.get("follower_count"))
        floor = rollups.pop("posts_90d_is_floor")
        reasons = list(profile.get("lane_reasons") or [])
        if floor:
            reasons.append("posts_90d_floor")
        patch.update(
            {
                **rollups,
                "hydrate_status": "complete",
                "hydrated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "stage": "hydrated",
                "work_status": "ready",
                "lane_reasons": reasons,
            }
        )
    store.update("creator_profiles", patch, id=profile["id"])
    return {"hydrate_status": patch.get("hydrate_status"), "null_rate": null_rate, "upserted": len(parsed)}
