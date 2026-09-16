"""Fetch a TikTok profile catalog via yt-dlp (package-native).

Account-scoped: the profile URL, per-video URLs and catalog filename all follow
`config.ACCOUNT`, so a peer library never wears DocMap's handle.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from marketing_pipeline import config

# Sentinel: distinguishes "no JSON parsed" from "parsed, value was null".
_UNPARSED = object()


def parse_since(s: str) -> float:
    dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return dt.timestamp()


def fetch_playlist(
    *,
    cookies_from_browser: str | None = None,
    handle: str | None = None,
    attempts: int = 3,
    playlist_end: int | None = None,
) -> dict:
    """List a profile's videos via yt-dlp.

    TikTok rejects these requests intermittently, so retry with backoff. stderr is
    captured rather than discarded: swallowing it turns a rate-limit into an
    unexplained CalledProcessError.
    """
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        config.profile_url(handle),
    ]
    if playlist_end is not None:
        cmd.extend(["--playlist-end", str(playlist_end)])
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])

    last_error = ""
    for attempt in range(1, attempts + 1):
        proc = subprocess.run(cmd, capture_output=True)
        # Exit code alone is not a success signal: yt-dlp exits 0 while printing
        # a bare `null` when an extraction yields nothing, and it can exit
        # non-zero after a partial extraction that still wrote usable JSON. Judge
        # the payload, not the status.
        # `null` parses to None, so a sentinel is needed to tell "nothing parsed"
        # apart from "parsed, and the value was null".
        payload: Any = _UNPARSED
        if proc.stdout.strip():
            try:
                payload = json.loads(proc.stdout.decode("utf-8"))
            except json.JSONDecodeError as exc:
                last_error = f"stdout was not JSON: {exc}"
        if isinstance(payload, dict) and payload.get("entries"):
            return payload

        if payload is _UNPARSED:
            if not last_error:
                last_error = (proc.stderr or b"").decode("utf-8", "replace").strip()
        elif isinstance(payload, dict):
            last_error = "yt-dlp returned a playlist with no entries"
        else:
            last_error = f"yt-dlp returned {payload!r} instead of a playlist"
        if attempt < attempts:
            # TikTok throttles the profile endpoint for minutes, not seconds.
            time.sleep(min(2**attempt * 15, 120))

    raise RuntimeError(
        f"yt-dlp could not list {config.profile_url(handle)} after {attempts} attempts. "
        f"Last stderr:\n{last_error[-1500:]}"
    )


def _num(value: Any) -> int | None:
    """Absent metrics are null, never "" or 0.

    A blank reads as "present but empty" downstream and silently satisfies
    coverage checks; a zero pollutes medians. Both must stay distinguishable
    from a real measurement.
    """
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def profile_meta(playlist: dict) -> dict[str, Any]:
    """Channel-level facts yt-dlp returns alongside the playlist.

    Follower count is the only available denominator for reach-beyond-audience,
    and the bio link is the clearest read on the off-platform ladder.
    """
    return {
        "handle": playlist.get("uploader_id") or playlist.get("uploader"),
        "channel": playlist.get("channel") or playlist.get("uploader"),
        "follower_count": _num(playlist.get("channel_follower_count")),
        "bio": (playlist.get("description") or "").strip() or None,
        "profile_url": playlist.get("channel_url") or playlist.get("uploader_url"),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def entry_to_row(e: dict, *, handle: str | None = None) -> dict:
    ts = e.get("timestamp")
    post_dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else ""
    post_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d") if ts else ""
    vid = str(e.get("id") or "")
    return {
        "video_id": vid,
        "post_date_utc": post_date,
        "post_datetime_utc": post_dt,
        "url": config.video_url(vid, handle),
        "title": (e.get("title") or "").replace("\r\n", " ").strip(),
        "description": (e.get("description") or "").replace("\r\n", " ").strip(),
        "duration_sec": _num(e.get("duration")),
        "view_count": _num(e.get("view_count")),
        "like_count": _num(e.get("like_count")),
        "comment_count": _num(e.get("comment_count")),
        "share_count": _num(e.get("repost_count")),
        "save_count": _num(e.get("save_count")),
    }


def _write_catalog(
    rows: list[dict], *, since: str, dest_dir: Path, handle: str | None = None
) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    json_path = dest_dir / config.catalog_filename(since, handle)
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path


def _coverage(rows: list[dict]) -> dict[str, int]:
    """Per-field non-null counts, so a sparse public catalog is visible."""
    fields = ("duration_sec", "view_count", "like_count", "comment_count", "share_count", "save_count")
    return {f: sum(1 for r in rows if r.get(f) is not None) for f in fields}


def fetch_catalog(
    *,
    since: str = "2026-04-20",
    cookies_from_browser: str | None = None,
    mirror_legacy: bool = False,
    handle: str | None = None,
) -> dict[str, Any]:
    handle = handle or config.ACCOUNT
    cutoff = parse_since(since)
    playlist = fetch_playlist(cookies_from_browser=cookies_from_browser, handle=handle)
    entries = playlist.get("entries") or []

    filtered: list[dict] = []
    dropped_null = 0
    for entry in entries:
        # A throttled listing yields null placeholders where an item failed to
        # extract. Skip them instead of dying three frames later on .get().
        if not isinstance(entry, dict):
            dropped_null += 1
            continue
        ts = entry.get("timestamp")
        if ts is None or ts < cutoff:
            continue
        filtered.append(entry_to_row(entry, handle=handle))
    filtered.sort(key=lambda r: r["post_datetime_utc"], reverse=True)

    if dropped_null and not filtered:
        raise RuntimeError(
            f"Listing for {config.profile_url(handle)} returned {dropped_null} null "
            "entries and no usable rows — almost certainly throttled. Refusing to "
            "overwrite the existing catalog with an empty one."
        )

    json_path = _write_catalog(filtered, since=since, dest_dir=config.CATALOG_DIR, handle=handle)

    meta = profile_meta(playlist)
    meta_path = config.CATALOG_DIR / f"{handle}_profile.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # Legacy mirror is opt-in only: package data/ is the single source of truth;
    # pass mirror_legacy=True when manually running old Social media analysis scripts.
    if mirror_legacy:
        legacy_data = config.LEGACY_TIKTOK_ROOT / "data"
        _write_catalog(filtered, since=since, dest_dir=legacy_data, handle=handle)

    return {
        "account": handle,
        "since": since,
        "entries": len(entries),
        "catalog_count": len(filtered),
        "catalog_path": str(json_path),
        "profile_path": str(meta_path),
        "follower_count": meta.get("follower_count"),
        "null_entries_skipped": dropped_null,
        "field_coverage": _coverage(filtered),
    }
