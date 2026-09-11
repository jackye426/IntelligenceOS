"""Download TikTok video media via yt-dlp."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from marketing_pipeline import config


def tiktok_url(video_id: str) -> str:
    return config.video_url(video_id)


def resolve_media_path(video_id: str) -> Path | None:
    for base in (config.MEDIA_DIR, config.LEGACY_MEDIA_DIR):
        for ext in ("mp4", "webm", "m4a", "mp3"):
            path = base / f"{video_id}.{ext}"
            if path.exists():
                return path
    return None


def has_audio_stream(path: Path) -> bool:
    """True when the container carries at least one audio stream.

    `-f best` can return a video-only HEVC rendition. Whisper then dies inside
    PyAV with "tuple index out of range", which reads like a library bug rather
    than a missing audio track, so check explicitly.
    """
    try:
        out = subprocess.run(
            [
                config.FFMPEG_PATH.replace("ffmpeg", "ffprobe"),
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        # ffprobe unavailable: don't block the download on an unverifiable check.
        return True
    return b"audio" in (out.stdout or b"")


def download_media(video_id: str, *, dest_dir: Path | None = None) -> Path:
    existing = resolve_media_path(video_id)
    if existing and existing.parent == (dest_dir or config.MEDIA_DIR):
        if has_audio_stream(existing):
            return existing
        # A previous run stored a video-only rendition. Replace it.
        existing.unlink()

    target = dest_dir or config.MEDIA_DIR
    target.mkdir(parents=True, exist_ok=True)
    dest_tpl = str(target / f"{video_id}.%(ext)s")
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-warnings",
        # Prefer a single format that already carries both streams (TikTok's
        # h264+aac rendition), then fall back to merging, then to anything.
        # Plain "best" ranks by resolution and so picks TikTok's 1080p HEVC
        # rendition, which is VIDEO ONLY — Whisper then fails deep inside PyAV.
        "-f",
        "b[vcodec!=none][acodec!=none]/bv*+ba/b",
        "--merge-output-format",
        "mp4",
        "-o",
        dest_tpl,
        tiktok_url(video_id),
    ]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    path = resolve_media_path(video_id)
    if not path:
        raise FileNotFoundError(f"No media downloaded for {video_id}")
    if not has_audio_stream(path):
        raise RuntimeError(
            f"Downloaded media for {video_id} has no audio stream ({path.name}). "
            "Transcription would fail; check the yt-dlp format selector."
        )
    return path
