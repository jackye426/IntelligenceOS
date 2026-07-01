"""
Pull public video metadata for @docmap from TikTok via yt-dlp (same feed as the profile).

Note: TikTok's web API may return a limited window of posts (often on the order of tens of
videos). If counts look low, try upgrading yt-dlp or passing browser cookies:

  python scripts/fetch_docmap_catalog.py --cookies-from-browser chrome

Outputs under data/: CSV + JSON catalog, and a CSV of videos not found in the content tracker.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
WORKSPACE = ROOT.parent
DEFAULT_TRACKER = WORKSPACE / "Marketing - Content - Tracker - Content Tracker (3).csv"
PROFILE_URL = "https://www.tiktok.com/@docmap"


def parse_since(s: str) -> float:
    """YYYY-MM-DD -> UTC start-of-day timestamp."""
    dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return dt.timestamp()


def load_tracker_video_ids(tracker_path: Path) -> set[str]:
    if not tracker_path.exists():
        return set()
    text = tracker_path.read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r"tiktok\.com/@docmap/video/(\d+)", text, flags=re.I))


def fetch_playlist(profile_url: str, *, cookies_from_browser: str | None) -> dict:
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        profile_url,
    ]
    if cookies_from_browser:
        cmd.append("--cookies-from-browser")
        cmd.append(cookies_from_browser)
    raw = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
    return json.loads(raw.decode("utf-8"))


def entry_to_row(e: dict, *, in_tracker: bool) -> dict:
    ts = e.get("timestamp")
    post_dt = (
        datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else ""
    )
    post_date = (
        datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        if ts
        else ""
    )
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
        "comment_count": e.get("comment_count")
        if e.get("comment_count") is not None
        else "",
        "share_count": e.get("repost_count")
        if e.get("repost_count") is not None
        else "",
        "save_count": e.get("save_count") if e.get("save_count") is not None else "",
        "in_content_tracker": "yes" if in_tracker else "no",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="List @docmap TikTok posts since a date.")
    ap.add_argument(
        "--since",
        default="2026-04-20",
        help="Include posts on or after this UTC date (YYYY-MM-DD). Default: 2026-04-20",
    )
    ap.add_argument(
        "--tracker",
        type=Path,
        default=DEFAULT_TRACKER,
        help="CSV content tracker to cross-check TT_Link column",
    )
    ap.add_argument(
        "--cookies-from-browser",
        metavar="BROWSER",
        default=None,
        help="e.g. chrome — may return more posts if TikTok gates the feed",
    )
    args = ap.parse_args()

    cutoff = parse_since(args.since)
    tracker_ids = load_tracker_video_ids(args.tracker)

    print("Fetching playlist from", PROFILE_URL, flush=True)
    playlist = fetch_playlist(PROFILE_URL, cookies_from_browser=args.cookies_from_browser)
    entries = playlist.get("entries") or []
    print(f"yt-dlp returned {len(entries)} entries (playlist_count={playlist.get('playlist_count')})", flush=True)

    filtered: list[dict] = []
    for e in entries:
        ts = e.get("timestamp")
        if ts is None or ts < cutoff:
            continue
        vid = str(e.get("id") or "")
        filtered.append(
            entry_to_row(e, in_tracker=(vid in tracker_ids if vid else False))
        )

    filtered.sort(key=lambda r: r["post_datetime_utc"], reverse=True)

    slug = args.since.replace("-", "")
    DATA.mkdir(parents=True, exist_ok=True)
    csv_path = DATA / f"docmap_catalog_since_{slug}.csv"
    json_path = DATA / f"docmap_catalog_since_{slug}.json"
    missing_path = DATA / f"docmap_missing_from_tracker_since_{slug}.csv"

    if filtered:
        fieldnames = list(filtered[0].keys())
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(filtered)
        json_path.write_text(
            json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        missing = [r for r in filtered if r["in_content_tracker"] == "no"]
        if missing:
            with missing_path.open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(missing)
        else:
            if missing_path.exists():
                missing_path.unlink()
    else:
        csv_path.write_text("", encoding="utf-8")
        json_path.write_text("[]", encoding="utf-8")

    n_miss = sum(1 for r in filtered if r["in_content_tracker"] == "no")
    print(f"Posts since {args.since} UTC: {len(filtered)}", flush=True)
    print(f"Not found in tracker: {n_miss}", flush=True)
    print("Wrote", csv_path, flush=True)
    print("Wrote", json_path, flush=True)
    if n_miss:
        print("Wrote", missing_path, flush=True)


if __name__ == "__main__":
    main()
