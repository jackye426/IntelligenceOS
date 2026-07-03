"""Fetch @docmap TikTok catalog via yt-dlp (package-native)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from marketing_pipeline import config

PROFILE_URL = "https://www.tiktok.com/@docmap"


def parse_since(s: str) -> float:
    dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return dt.timestamp()


def fetch_playlist(*, cookies_from_browser: str | None = None) -> dict:
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        PROFILE_URL,
    ]
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
    raw = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
    return json.loads(raw.decode("utf-8"))


def entry_to_row(e: dict) -> dict:
    ts = e.get("timestamp")
    post_dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else ""
    post_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d") if ts else ""
    vid = str(e.get("id") or "")
    return {
        "video_id": vid,
        "post_date_utc": post_date,
        "post_datetime_utc": post_dt,
        "url": f"https://www.tiktok.com/@docmap/video/{vid}",
        "title": (e.get("title") or "").replace("\r\n", " ").strip(),
        "description": (e.get("description") or "").replace("\r\n", " ").strip(),
        "duration_sec": e.get("duration") or "",
        "view_count": e.get("view_count") if e.get("view_count") is not None else "",
        "like_count": e.get("like_count") if e.get("like_count") is not None else "",
        "comment_count": e.get("comment_count") if e.get("comment_count") is not None else "",
        "share_count": e.get("repost_count") if e.get("repost_count") is not None else "",
        "save_count": e.get("save_count") if e.get("save_count") is not None else "",
    }


def _write_catalog(rows: list[dict], *, since: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    slug = since.replace("-", "")
    json_path = dest_dir / f"docmap_catalog_since_{slug}.json"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path


def fetch_catalog(
    *,
    since: str = "2026-04-20",
    cookies_from_browser: str | None = None,
    mirror_legacy: bool = True,
) -> dict[str, int | str]:
    cutoff = parse_since(since)
    playlist = fetch_playlist(cookies_from_browser=cookies_from_browser)
    entries = playlist.get("entries") or []

    filtered: list[dict] = []
    for entry in entries:
        ts = entry.get("timestamp")
        if ts is None or ts < cutoff:
            continue
        filtered.append(entry_to_row(entry))
    filtered.sort(key=lambda r: r["post_datetime_utc"], reverse=True)

    json_path = _write_catalog(filtered, since=since, dest_dir=config.CATALOG_DIR)
    if mirror_legacy:
        legacy_data = config.LEGACY_TIKTOK_ROOT / "data"
        _write_catalog(filtered, since=since, dest_dir=legacy_data)

    return {
        "since": since,
        "entries": len(entries),
        "catalog_count": len(filtered),
        "catalog_path": str(json_path),
    }
