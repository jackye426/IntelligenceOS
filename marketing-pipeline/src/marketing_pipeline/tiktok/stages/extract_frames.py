"""Extract video frames at hook timestamps."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from marketing_pipeline import config

DEFAULT_TIMESTAMPS = (0.0, 0.5, 1.0, 2.0)
CAROUSEL_TIMESTAMPS = (0.0, 1.0, 2.0, 3.0, 4.0)


def _ffmpeg_bin() -> str:
    return config.FFMPEG_PATH or "ffmpeg"


def extract_frame(media_path: Path, timestamp_sec: float, output_path: Path) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.stat().st_size > 0:
        return True
    if not shutil.which(_ffmpeg_bin()) and config.FFMPEG_PATH == "ffmpeg":
        return False
    cmd = [
        _ffmpeg_bin(),
        "-y",
        "-ss",
        str(timestamp_sec),
        "-i",
        str(media_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        return output_path.exists() and output_path.stat().st_size > 0
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def extract_hook_frames(
    video_id: str,
    media_path: Path,
    *,
    carousel: bool = False,
) -> list[Path]:
    stamps = CAROUSEL_TIMESTAMPS if carousel else DEFAULT_TIMESTAMPS
    frame_dir = config.OCR_CACHE_DIR / "frames" / video_id
    frames: list[Path] = []
    for ts in stamps:
        out = frame_dir / f"frame_{ts:.1f}s.jpg"
        if extract_frame(media_path, ts, out):
            frames.append(out)
    return frames
