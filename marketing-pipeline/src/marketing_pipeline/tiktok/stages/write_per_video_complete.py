"""Write per-video COMPLETE transcript files."""

from __future__ import annotations

import json
from pathlib import Path

from marketing_pipeline import config
from marketing_pipeline.tiktok.stages.download_media import tiktok_url


def write_complete_transcript(
    video_id: str,
    full_text: str,
    *,
    title: str | None,
    description: str | None,
    webpage_url: str | None = None,
    out_dir: Path | None = None,
) -> Path:
    target = out_dir or config.TRANSCRIPTS_DIR
    target.mkdir(parents=True, exist_ok=True)
    lines = [
        f"video_id: {video_id}\n",
        f"url: {webpage_url or tiktok_url(video_id)}\n",
        "\n",
        "## Spoken transcript (Whisper automatic speech recognition, English)\n",
        (
            full_text.strip()
            if full_text.strip()
            else "(No clear speech detected in the downloaded audio track.)"
        ),
        "\n",
    ]
    t = (title or "").strip()
    d = (description or "").strip()
    if t or d:
        lines.append("\n## TikTok title and description (verbatim from post metadata)\n\n")
        if d and t:
            td = t.rstrip("….").strip()
            if d.startswith(td) or td in d[:120]:
                lines.append(d.rstrip() + "\n")
            else:
                lines.append(f"{t}\n\n{d.rstrip()}\n")
        elif d:
            lines.append(d.rstrip() + "\n")
        else:
            lines.append(t + "\n")
    path = target / f"{video_id}_COMPLETE.txt"
    path.write_text("".join(lines), encoding="utf-8")
    return path


def ensure_complete_from_json(video_id: str, meta: dict, *, out_dir: Path | None = None) -> Path | None:
    jp = (out_dir or config.TRANSCRIPTS_DIR) / f"{video_id}.json"
    if not jp.exists():
        complete = (out_dir or config.TRANSCRIPTS_DIR) / f"{video_id}_COMPLETE.txt"
        if complete.exists():
            complete.unlink()
        return None
    data = json.loads(jp.read_text(encoding="utf-8"))
    full_text = data.get("full_text")
    if full_text is None and isinstance(data, list):
        full_text = " ".join(s.get("text", "") for s in data).strip()
    return write_complete_transcript(
        video_id,
        full_text or "",
        title=meta.get("title"),
        description=meta.get("description"),
        webpage_url=meta.get("webpage_url"),
        out_dir=out_dir,
    )


def existing_complete_ids(*, transcripts_dir: Path | None = None) -> set[str]:
    root = transcripts_dir or config.TRANSCRIPTS_DIR
    return {
        p.name.replace("_COMPLETE.txt", "")
        for p in root.glob("*_COMPLETE.txt")
        if p.name != "ALL_COMPLETE_TRANSCRIPTS.txt"
    }
