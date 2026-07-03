"""Fetch and cache TikTok video metadata via yt-dlp."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from marketing_pipeline import config
from marketing_pipeline.tiktok.stages.download_media import tiktok_url


def fetch_yt_meta(video_id: str, *, cache: bool = True) -> dict:
    path = config.YT_META_DIR / f"{video_id}.json"
    if cache and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-warnings",
        "--dump-json",
        "--no-download",
        "-o",
        str(config.YT_META_DIR / "%(id)s"),
        tiktok_url(video_id),
    ]
    config.YT_META_DIR.mkdir(parents=True, exist_ok=True)
    raw = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
    data = json.loads(raw.decode("utf-8"))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def metrics_from_meta(meta: dict, *, catalog_row: dict | None = None) -> dict:
    views = int(meta.get("view_count") or 0)
    likes = int(meta.get("like_count") or 0)
    comments = int(meta.get("comment_count") or 0)
    shares = int(meta.get("repost_count") or 0)
    saves = int(str(meta.get("save_count") or "0").replace(",", "") or 0)
    dur = float(meta.get("duration") or 0)
    row = catalog_row or {}
    return {
        "video_id": str(meta.get("id") or row.get("video_id") or ""),
        "post_date_utc": row.get("post_date_utc"),
        "url": row.get("url") or meta.get("webpage_url"),
        "title": meta.get("title") or row.get("title"),
        "description": meta.get("description") or row.get("description"),
        "duration_sec": dur,
        "view_count": views,
        "like_count": likes,
        "comment_count": comments,
        "share_count": shares,
        "save_count": saves,
        "like_per_1k_views": round(1000 * likes / views, 4) if views else None,
        "comment_per_1k_views": round(1000 * comments / views, 4) if views else None,
        "share_per_1k_views": round(1000 * shares / views, 4) if views else None,
        "save_per_1k_views": round(1000 * saves / views, 4) if views else None,
    }


def analytics_dict(meta: dict) -> dict:
    upload = meta.get("upload_date")
    post_date = ""
    if upload and len(str(upload)) == 8:
        post_date = f"{upload[:4]}-{upload[4:6]}-{upload[6:8]}"
    return {
        "view_count": int(meta.get("view_count") or 0) if meta.get("view_count") is not None else None,
        "like_count": int(meta.get("like_count") or 0) if meta.get("like_count") is not None else None,
        "comment_count": int(meta.get("comment_count") or 0)
        if meta.get("comment_count") is not None
        else None,
        "save_count": int(str(meta.get("save_count") or "0").replace(",", "") or 0)
        if meta.get("save_count") is not None
        else None,
        "share_count": int(meta.get("repost_count") or 0) if meta.get("repost_count") is not None else None,
        "post_timestamp": meta.get("timestamp"),
        "upload_date": upload,
        "post_date_utc": post_date or None,
        "duration_sec": meta.get("duration"),
    }
