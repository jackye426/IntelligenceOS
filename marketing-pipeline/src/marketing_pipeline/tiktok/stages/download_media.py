"""Download TikTok video media via yt-dlp."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from marketing_pipeline import config


def tiktok_url(video_id: str) -> str:
    return f"https://www.tiktok.com/@docmap/video/{video_id}"


def resolve_media_path(video_id: str) -> Path | None:
    for base in (config.MEDIA_DIR, config.LEGACY_MEDIA_DIR):
        for ext in ("mp4", "webm", "m4a", "mp3"):
            path = base / f"{video_id}.{ext}"
            if path.exists():
                return path
    return None


def download_media(video_id: str, *, dest_dir: Path | None = None) -> Path:
    existing = resolve_media_path(video_id)
    if existing and existing.parent == (dest_dir or config.MEDIA_DIR):
        return existing

    target = dest_dir or config.MEDIA_DIR
    target.mkdir(parents=True, exist_ok=True)
    dest_tpl = str(target / f"{video_id}.%(ext)s")
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-warnings",
        "-f",
        "best",
        "-o",
        dest_tpl,
        tiktok_url(video_id),
    ]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    path = resolve_media_path(video_id)
    if path:
        return path
    raise FileNotFoundError(f"No media downloaded for {video_id}")
