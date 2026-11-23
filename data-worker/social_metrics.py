"""Fresh social observations; scheduled independently of enrichment/embeddings."""
from datetime import datetime, timezone
from itertools import islice
import json
import os
from pathlib import Path
import re
import subprocess
import sys

TARGETS = {"tiktok": ("docmap", "endobowelsurgeon"),
           "instagram": ("docmapuk", "endobowelsurgeon")}
FIELDS = {
    "tiktok": {"views": "view_count", "likes": "like_count",
               "comments": "comment_count", "shares": "repost_count", "saves": "save_count"},
    "instagram": {"views": "video_view_count", "likes": "likes", "comments": "comments"},
}
SOURCES = {"tiktok": "yt_dlp", "instagram": "instaloader"}

def tiktok_posts(handle):
    # Keep existing third-party yt-dlp ingestion, without official API fallback.
    output = subprocess.check_output(
        [sys.executable, "-m", "yt_dlp", "--flat-playlist", "--playlist-end", "80",
         "--dump-single-json", "--no-warnings", f"https://www.tiktok.com/@{handle}"],
        stderr=subprocess.DEVNULL, timeout=120,
    )
    result = json.loads(output)
    entries = result.get("entries")
    uploader = str(result.get("uploader_id") or result.get("uploader") or "").lstrip("@").lower()
    if uploader and uploader != handle and not all(
        f"/@{handle}/video/" in str(row.get("url") or row.get("webpage_url") or "")
        for row in (entries or []) if isinstance(row, dict)
    ):
        raise ValueError("unexpected TikTok owner")
    if not isinstance(entries, list):
        raise ValueError("missing TikTok entries")
    return entries

def instagram_posts(handle):
    import instaloader
    loader = instaloader.Instaloader(quiet=True, max_connection_attempts=1,
                                    request_timeout=30)
    session_user = os.getenv("SOCIAL_INSTAGRAM_SESSION_USER")
    session_file = os.getenv("SOCIAL_INSTAGRAM_SESSION_FILE")
    if bool(session_user) != bool(session_file):
        raise ValueError("configure both Instagram session fields or neither")
    if session_file:
        if not Path(session_file).is_file():
            raise FileNotFoundError("Instagram session file unavailable")
        loader.load_session_from_file(session_user, session_file)
    profile = instaloader.Profile.from_username(loader.context, handle)
    if profile.username.lower() != handle:
        raise ValueError("unexpected Instagram owner")
    return [{"id": str(p.mediaid), "shortcode": p.shortcode, "timestamp": p.date_utc,
             "likes": p.likes, "comments": p.comments,
             "video_view_count": p.video_view_count if p.is_video else None}
            for p in islice(profile.get_posts(), 80)]

def observations(platform, handle, rows):
    for row in rows:
        if not isinstance(row, dict):
            continue
        post_id = str(row.get("id") or "")
        if not re.fullmatch(r"[0-9]{5,25}", post_id):
            continue
        if platform == "tiktok":
            original = str(row.get("url") or row.get("webpage_url") or "")
            url = f"https://www.tiktok.com/@{handle}/video/{post_id}"
            if original.startswith("http") and original.split("?", 1)[0].rstrip("/") != url:
                continue
        else:
            shortcode = str(row.get("shortcode") or "")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", shortcode):
                continue
            url = f"https://www.instagram.com/p/{shortcode}/"
        metrics = {name: row[key] for name, key in FIELDS[platform].items()
                   if type(row.get(key)) is int and row[key] >= 0}
        if not metrics:
            continue
        posted = row.get("timestamp")
        if type(posted) is int and 0 < posted < 4102444800:
            posted = datetime.fromtimestamp(posted, timezone.utc)
        if isinstance(posted, datetime) and posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        yield post_id, url, posted.isoformat() if isinstance(posted, datetime) else None, metrics

def write_snapshot(client, platform, handle, observation, captured_at):
    post_id, url, posted_at, metrics = observation
    table = client.table("content_posts")
    existing = (table.select("id,account_handle").eq("platform", platform)
                .eq("platform_post_id", post_id).limit(1).execute().data or [])
    if existing:
        row = existing[0]
        if row["account_handle"] not in (handle, "docmap" if handle == "docmapuk" else handle):
            raise ValueError("content post ownership conflict")
    else:
        row = table.insert({
            "platform": platform, "platform_post_id": post_id, "post_url": url,
            "posted_at": posted_at, "account_handle": handle,
            "owner_scope": "peer:endobowelsurgeon" if handle == "endobowelsurgeon" else "docmap",
            "title": f"{handle} {platform} post", "metrics": metrics,
            "metadata": {"is_catalog_stub": True, "source": SOURCES[platform]},
        }).execute().data[0]
    client.table("content_metric_snapshots").insert({
        "platform": platform, "platform_post_id": post_id, "content_post_id": row["id"],
        "captured_at": captured_at, "source": SOURCES[platform], "metrics": metrics,
    }).execute()

def refresh(*, save, enrich=None, fetchers=None, targets=TARGETS, clock=None):
    """All save callbacks complete before invoking any optional enrichment."""
    fetchers = fetchers or {"tiktok": tiktok_posts, "instagram": instagram_posts}
    clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
    result = {}
    for platform, handles in targets.items():
        for handle in handles:
            target = f"{platform}:{handle}"
            try:
                rows = list(observations(platform, handle, fetchers[platform](handle)))
            except Exception as exc:
                result[target] = {"status": "fetch_failed", "error_type": type(exc).__name__}
                continue
            if not rows:
                result[target] = {"status": "no_fresh_observations", "saved": 0}
                continue
            captured = clock()
            count = 0
            for observation in rows:
                try:
                    save(platform, handle, observation, captured)
                    count += 1
                except Exception:
                    # Continue unrelated records and explicitly disclose failures.
                    pass
            result[target] = {"status": "saved" if count == len(rows) else "save_failed",
                              "saved": count, "observed": len(rows)}
    if enrich is not None and all(value["status"] == "saved" for value in result.values()):
        try:
            enrich()
            result["enrichment"] = {"status": "ok"}
        except Exception as exc:
            result["enrichment"] = {"status": "failed", "error_type": type(exc).__name__}
    return result
