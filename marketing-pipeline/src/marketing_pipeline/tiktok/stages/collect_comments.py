"""Fetch TikTok comments from catalog video IDs."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from marketing_pipeline import config
from marketing_pipeline.tiktok.stages.collect_catalog import load_catalog

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def fetch_comment_page(aweme_id: str, cursor: int = 0, count: int = 50) -> dict:
    query = urllib.parse.urlencode(
        {
            "aid": "1988",
            "aweme_id": aweme_id,
            "count": str(count),
            "cursor": str(cursor),
        }
    )
    url = f"https://www.tiktok.com/api/comment/list/?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Referer": "https://www.tiktok.com/",
            "Accept": "application/json, text/plain, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_all_comments(aweme_id: str, max_comments: int = 500) -> list[dict]:
    out: list[dict] = []
    cursor = 0
    retries = 0
    while len(out) < max_comments:
        try:
            data = fetch_comment_page(aweme_id, cursor=cursor, count=50)
            retries = 0
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429) and retries < 3:
                retries += 1
                time.sleep(2**retries)
                continue
            raise
        comments = data.get("comments") or []
        if not comments:
            break
        for item in comments:
            out.append(
                {
                    "cid": item.get("cid"),
                    "text": (item.get("text") or "").strip(),
                    "digg_count": int(item.get("digg_count") or 0),
                    "reply_comment_total": int(item.get("reply_comment_total") or 0),
                    "create_time": item.get("create_time"),
                }
            )
            if len(out) >= max_comments:
                break
        if not data.get("has_more"):
            break
        cursor = int(data.get("cursor") or 0)
        time.sleep(0.35)
    return out


def _file_age_days(path: Path) -> float:
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - mtime).total_seconds() / 86400


def needs_refresh(
    video_id: str,
    *,
    catalog_comment_count: int | None = None,
    stale_days: int | None = None,
) -> bool:
    path = config.COMMENTS_RAW_DIR / f"{video_id}.json"
    if not path.exists():
        return True
    days = stale_days if stale_days is not None else config.COMMENT_STALE_DAYS
    if _file_age_days(path) > days:
        return True
    if catalog_comment_count is not None:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if catalog_comment_count > len(existing):
                return True
        except json.JSONDecodeError:
            return True
    return False


def collect_comments(
    *,
    max_comments: int = 500,
    force: bool = False,
    stale_days: int | None = None,
) -> dict[str, int]:
    catalog = load_catalog(config.CATALOG_DIR)
    config.COMMENTS_RAW_DIR.mkdir(parents=True, exist_ok=True)
    counts = {"seen": 0, "fetched": 0, "skipped": 0, "errors": 0}

    for video_id, row in catalog.items():
        counts["seen"] += 1
        comment_count = int(row.get("comment_count") or 0)
        if not force and not needs_refresh(
            video_id,
            catalog_comment_count=comment_count,
            stale_days=stale_days,
        ):
            counts["skipped"] += 1
            continue
        dest = config.COMMENTS_RAW_DIR / f"{video_id}.json"
        try:
            comments = fetch_all_comments(video_id, max_comments=max_comments)
            dest.write_text(json.dumps(comments, ensure_ascii=False, indent=2), encoding="utf-8")
            counts["fetched"] += 1
            time.sleep(0.5)
        except Exception:  # noqa: BLE001
            counts["errors"] += 1
    return counts
