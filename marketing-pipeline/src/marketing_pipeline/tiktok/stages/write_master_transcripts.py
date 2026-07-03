"""Compile ALL_COMPLETE_TRANSCRIPTS.txt from per-video COMPLETE files."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from marketing_pipeline import config
from marketing_pipeline.tiktok.stages.yt_meta import analytics_dict, fetch_yt_meta


def _parse_video_id(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("video_id:"):
            return line.split(":", 1)[1].strip()
    raise ValueError(f"no video_id line in {path}")


def _video_id_from_path(path: Path) -> str:
    try:
        return _parse_video_id(path)
    except ValueError:
        return path.stem.replace("_COMPLETE", "")


def _format_analytics(m: dict) -> list[str]:
    def fmt(key: str) -> str:
        v = m.get(key)
        return f"{v:,}" if isinstance(v, int) else "n/a"

    post = m.get("upload_date") or m.get("post_date_utc") or ""
    if post and len(str(post)) == 8:
        post = f"{post[:4]}-{post[4:6]}-{post[6:8]}"
    dur = m.get("duration_sec")
    dur_s = f"{dur}s" if dur is not None else "n/a"

    return [
        "## Analytics (public TikTok counts)",
        f"- Post date (UTC): {post or 'n/a'}",
        f"- Duration: {dur_s}",
        f"- Views: {fmt('view_count')}",
        f"- Likes: {fmt('like_count')}",
        f"- Comments: {fmt('comment_count')}",
        f"- Saves: {fmt('save_count')}",
        f"- Shares: {fmt('share_count')}",
        "",
    ]


def _comment_score(comment: dict) -> int:
    likes = int(comment.get("digg_count") or 0)
    replies = int(comment.get("reply_comment_total") or 0)
    return likes * 1000 + replies


def _load_comments(video_id: str) -> list[dict] | None:
    path = config.COMMENTS_RAW_DIR / f"{video_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else None
    except json.JSONDecodeError:
        return None


def _top_comments_block(video_id: str, *, top_n: int = 12) -> list[str]:
    lines = [
        "## Top comments (ranked by comment likes; reply count breaks ties)",
        "",
    ]
    comments = _load_comments(video_id)
    if comments is None:
        lines.append(
            "(No cached comments in comments_raw/. Run: python -m marketing_pipeline tiktok refresh-comments)"
        )
        lines.append("")
        return lines
    if not comments:
        lines.append("(No comments returned for this video.)")
        lines.append("")
        return lines

    ranked = sorted(comments, key=_comment_score, reverse=True)[:top_n]
    for i, comment in enumerate(ranked, start=1):
        text = (comment.get("text") or "").replace("\r\n", " ").replace("\n", " ").strip()
        text = re.sub(r"\s+", " ", text)
        if len(text) > 500:
            text = text[:497] + "..."
        likes = int(comment.get("digg_count") or 0)
        rep = int(comment.get("reply_comment_total") or 0)
        lines.append(f"{i}. {likes:,} likes, {rep:,} replies — {text}")
    lines.append("")
    return lines


def _spoken_hook(video_id: str, *, transcripts_dir: Path) -> str:
    jp = transcripts_dir / f"{video_id}.json"
    if not jp.exists():
        return ""
    data = json.loads(jp.read_text(encoding="utf-8"))
    full_text = data.get("full_text", "")
    if not full_text and isinstance(data, list):
        full_text = " ".join(s.get("text", "") for s in data).strip()
    if not full_text:
        return ""
    match = re.search(r"[.!?](?:\s|$)", full_text)
    if match and match.start() < 300:
        return full_text[: match.start() + 1].strip()
    return full_text.split("\n")[0].strip()[:250]


def write_master_transcripts(
    *,
    refresh_metrics: bool = True,
    include_comments: bool = True,
    top_comments: int = 12,
    out_path: Path | None = None,
    transcripts_dir: Path | None = None,
) -> dict[str, str | int]:
    trans_dir = transcripts_dir or config.TRANSCRIPTS_DIR
    master = out_path or config.MASTER_TRANSCRIPTS
    files = sorted(trans_dir.glob("*_COMPLETE.txt"))
    files = [p for p in files if p.name != master.name]
    if not files:
        raise FileNotFoundError(f"no *_COMPLETE.txt under {trans_dir}")

    metrics_cache: dict[str, dict] = {}
    for path in files:
        vid = _video_id_from_path(path)
        try:
            meta = fetch_yt_meta(vid, cache=not refresh_metrics)
            metrics_cache[vid] = analytics_dict(meta)
        except Exception:  # noqa: BLE001
            metrics_cache[vid] = {}

    def sort_key(path: Path) -> tuple:
        vid = _video_id_from_path(path)
        ts = metrics_cache.get(vid, {}).get("post_timestamp")
        if ts is not None:
            return (-int(ts), vid)
        return (0, vid)

    files.sort(key=sort_key)
    refreshed = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    blocks = [
        "# Docmap TikTok — all COMPLETE transcripts (spoken ASR + TikTok caption metadata)",
        "# Regenerated by marketing_pipeline.tiktok.stages.write_master_transcripts",
        f"# Videos: {len(files)} | Sorted: post date, newest first",
        f"# Analytics & comments refreshed: {refreshed}",
        "# Comments source: comments_raw cache",
        "",
    ]

    for i, path in enumerate(files, start=1):
        vid = _parse_video_id(path)
        body = path.read_text(encoding="utf-8").rstrip()
        blocks.append("=" * 80)
        blocks.append(f"VIDEO {i} / {len(files)} — id {vid}")
        blocks.append("=" * 80)
        blocks.append("")

        metrics = metrics_cache.get(vid) or {}
        if metrics:
            blocks.extend(_format_analytics(metrics))
        else:
            blocks.append("## Analytics")
            blocks.append("(Could not load metrics)")
            blocks.append("")

        if include_comments:
            blocks.extend(_top_comments_block(vid, top_n=top_comments))

        hook = _spoken_hook(vid, transcripts_dir=trans_dir)
        blocks.append("## Hook (first spoken sentence)")
        blocks.append(f'"{hook}"' if hook else "(no speech detected)")
        blocks.append("")
        blocks.append(body)
        blocks.append("")

    blocks.extend(["=" * 80, "END", "=" * 80, ""])
    master.parent.mkdir(parents=True, exist_ok=True)
    master.write_text("\n".join(blocks), encoding="utf-8")
    return {"master_path": str(master), "videos": len(files)}
