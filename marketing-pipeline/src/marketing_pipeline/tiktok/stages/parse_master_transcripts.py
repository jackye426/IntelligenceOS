"""Parse ALL_COMPLETE_TRANSCRIPTS.txt into structured video dicts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

VIDEO_BLOCK_RE = re.compile(
    r"={80,}\nVIDEO \d+ / \d+ — id (\d+)\n={80,}\n(.*?)(?=\n={80,}\nVIDEO |\Z)",
    re.DOTALL,
)
INT_RE = re.compile(r"[\d,]+")


def _parse_int(text: str | None) -> int | None:
    if not text:
        return None
    match = INT_RE.search(text.replace(",", ""))
    if not match:
        return None
    try:
        return int(match.group().replace(",", ""))
    except ValueError:
        return None


def _section_field(block: str, label: str) -> str | None:
    match = re.search(rf"^- {re.escape(label)}:\s*(.+)$", block, re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip()


def parse_video_block(video_id: str, block: str) -> dict[str, Any]:
    hook_match = re.search(
        r'## Hook \(first spoken sentence\)\n"(.+?)"',
        block,
        re.DOTALL,
    )
    transcript_match = re.search(
        r"## Spoken transcript.*?\n(.*?)(?:\n## TikTok title|\Z)",
        block,
        re.DOTALL,
    )
    caption_match = re.search(
        r"## TikTok title and description.*?\n\n(.+?)(?:\n={80,}|\Z)",
        block,
        re.DOTALL,
    )
    url_match = re.search(r"^url:\s*(.+)$", block, re.MULTILINE)
    post_url = (
        url_match.group(1).strip()
        if url_match
        else f"https://www.tiktok.com/@docmap/video/{video_id}"
    )

    caption = caption_match.group(1).strip() if caption_match else None
    transcript = transcript_match.group(1).strip() if transcript_match else None
    hook = hook_match.group(1).strip() if hook_match else None

    post_date = _section_field(block, "Post date (UTC)")
    posted_at = f"{post_date}T00:00:00+00:00" if post_date else None

    duration_raw = _section_field(block, "Duration")
    duration_sec = (
        _parse_int(duration_raw.replace("s", "").strip()) if duration_raw else None
    )

    views = _parse_int(_section_field(block, "Views"))
    metrics = {
        "views": views,
        "likes": _parse_int(_section_field(block, "Likes")),
        "comments": _parse_int(_section_field(block, "Comments")),
        "saves": _parse_int(_section_field(block, "Saves")),
        "shares": _parse_int(_section_field(block, "Shares")),
        "duration_sec": duration_sec,
    }
    if views and views > 0:
        for key, raw in [
            ("saves_per_1k_views", metrics.get("saves")),
            ("comments_per_1k_views", metrics.get("comments")),
            ("shares_per_1k_views", metrics.get("shares")),
        ]:
            if raw is not None:
                metrics[key] = round((raw / views) * 1000, 2)

    metrics = {k: v for k, v in metrics.items() if v is not None}

    return {
        "video_id": video_id,
        "url": post_url,
        "posted_at": posted_at,
        "caption": caption,
        "duration_sec": duration_sec,
        "spoken_hook": hook,
        "transcript": transcript,
        "metrics": metrics,
    }


def parse_master_transcripts(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    videos: list[dict[str, Any]] = []
    for video_id, block in VIDEO_BLOCK_RE.findall(text):
        videos.append(parse_video_block(video_id, block))
    return videos
