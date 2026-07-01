"""Concatenate all data/transcripts/*_COMPLETE.txt into ALL_COMPLETE_TRANSCRIPTS.txt.

Optionally appends per-video analytics (views, likes, comments, saves, shares) and
top comments by like count (TikTok web API), then regenerates the master file.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TRANS = ROOT / "data" / "transcripts"
META = DATA / "yt_meta"
OUT = TRANS / "ALL_COMPLETE_TRANSCRIPTS.txt"

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from fetch_comments import fetch_all_comments  # noqa: E402


def parse_video_id(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("video_id:"):
            return line.split(":", 1)[1].strip()
    raise ValueError(f"no video_id line in {path}")


def _int_metric(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, int):
        return v
    s = str(v).replace(",", "").strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def fetch_yt_meta(video_id: str) -> dict:
    url = f"https://www.tiktok.com/@docmap/video/{video_id}"
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-warnings",
        "--dump-json",
        "--no-download",
        "-o",
        str(META / "%(id)s"),
        url,
    ]
    out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
    raw = json.loads(out.decode("utf-8"))
    META.mkdir(parents=True, exist_ok=True)
    (META / f"{video_id}.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return raw


def load_or_fetch_metrics(video_id: str, *, refresh: bool) -> dict[str, int | None]:
    path = META / f"{video_id}.json"
    if refresh or not path.exists():
        raw = fetch_yt_meta(video_id)
    else:
        raw = json.loads(path.read_text(encoding="utf-8"))

    return {
        "view_count": _int_metric(raw.get("view_count")),
        "like_count": _int_metric(raw.get("like_count")),
        "comment_count": _int_metric(raw.get("comment_count")),
        "share_count": _int_metric(raw.get("repost_count")),
        "save_count": _int_metric(raw.get("save_count")),
        "post_timestamp": raw.get("timestamp"),
        "upload_date": raw.get("upload_date"),
        "duration_sec": raw.get("duration"),
    }


def video_id_from_path(path: Path) -> str:
    try:
        return parse_video_id(path)
    except ValueError:
        return path.stem.replace("_COMPLETE", "")


def prefetch_metrics(video_ids: list[str], *, refresh: bool) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i, vid in enumerate(video_ids, start=1):
        print(f"  metrics {i}/{len(video_ids)} {vid}", flush=True)
        try:
            out[vid] = load_or_fetch_metrics(vid, refresh=refresh)
        except Exception as e:
            print(f"    failed: {e}", flush=True)
            out[vid] = {}
    return out


def format_analytics(m: dict[str, int | None]) -> list[str]:
    def fmt(k: str) -> str:
        v = m.get(k)
        return f"{v:,}" if isinstance(v, int) else "n/a"

    post = m.get("upload_date") or ""
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


def comment_interaction_score(c: dict) -> int:
    likes = int(c.get("digg_count") or 0)
    replies = int(c.get("reply_comment_total") or 0)
    return likes * 1000 + replies


def top_comments_block(
    video_id: str,
    *,
    top_n: int,
    max_fetch: int,
) -> list[str]:
    lines: list[str] = [
        "## Top comments (ranked by comment likes; reply count breaks ties)",
        "",
    ]
    try:
        all_c = fetch_all_comments(video_id, max_comments=max_fetch)
        time.sleep(0.25)
    except Exception as e:
        lines.append(f"(Could not load comments: {e})")
        lines.append("")
        return lines

    if not all_c:
        lines.append("(No comments returned by TikTok API for this video.)")
        lines.append("")
        return lines

    ranked = sorted(all_c, key=comment_interaction_score, reverse=True)[:top_n]
    for i, c in enumerate(ranked, start=1):
        text = (c.get("text") or "").replace("\r\n", " ").replace("\n", " ").strip()
        text = re.sub(r"\s+", " ", text)
        if len(text) > 500:
            text = text[:497] + "..."
        likes = int(c.get("digg_count") or 0)
        rep = int(c.get("reply_comment_total") or 0)
        lines.append(f"{i}. {likes:,} likes, {rep:,} replies — {text}")
    lines.append("")
    return lines


def extract_spoken_hook(video_id: str) -> str:
    """Return the first sentence of the Whisper transcript for this video."""
    jp = DATA / "transcripts" / f"{video_id}.json"
    if not jp.exists():
        return ""
    data = json.loads(jp.read_text(encoding="utf-8"))
    full_text = data.get("full_text", "")
    if not full_text and isinstance(data, list):
        full_text = " ".join(s.get("text", "") for s in data).strip()
    if not full_text:
        return ""
    m = re.search(r"[.!?](?:\s|$)", full_text)
    if m and m.start() < 300:
        return full_text[: m.start() + 1].strip()
    return full_text.split("\n")[0].strip()[:250]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--no-comments",
        action="store_true",
        help="Skip TikTok comment API (faster, offline-friendly)",
    )
    ap.add_argument(
        "--top-comments",
        type=int,
        default=12,
        help="How many top comments to include per video",
    )
    ap.add_argument(
        "--comment-fetch-max",
        type=int,
        default=300,
        help="Max top-level comments to pull before ranking",
    )
    ap.add_argument(
        "--use-cache",
        action="store_true",
        help="Use cached yt_meta JSON instead of re-fetching TikTok stats",
    )
    args = ap.parse_args()

    refresh_metrics = not args.use_cache
    files = sorted(TRANS.glob("*_COMPLETE.txt"))
    files = [p for p in files if p.name != OUT.name]
    if not files:
        raise SystemExit(f"no *_COMPLETE.txt under {TRANS}")

    video_ids = [video_id_from_path(p) for p in files]
    print(f"Loading metrics for {len(files)} videos...", flush=True)
    metrics_cache = prefetch_metrics(video_ids, refresh=refresh_metrics)

    def sort_key(path: Path) -> tuple:
        vid = video_id_from_path(path)
        ts = metrics_cache.get(vid, {}).get("post_timestamp")
        if ts is not None:
            return (-int(ts), vid)
        return (0, vid)

    files.sort(key=sort_key)
    print("Sorted by post date (newest first).", flush=True)

    refreshed = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    blocks = [
        "# Docmap TikTok — all COMPLETE transcripts (spoken ASR + TikTok caption metadata)",
        "# Regenerated by scripts/compile_complete_transcripts.py",
        f"# Videos: {len(files)} | Sorted: post date, newest first",
        f"# Analytics & comments refreshed: {refreshed}",
        "",
    ]
    for i, path in enumerate(files, start=1):
        vid = parse_video_id(path)
        body = path.read_text(encoding="utf-8").rstrip()

        blocks.append("=" * 80)
        blocks.append(f"VIDEO {i} / {len(files)} — id {vid}")
        blocks.append("=" * 80)
        blocks.append("")

        try:
            metrics = metrics_cache.get(vid) or {}
            if metrics:
                blocks.extend(format_analytics(metrics))
            else:
                raise ValueError("no metrics available")
        except Exception as e:
            blocks.append("## Analytics")
            blocks.append(f"(Could not load metrics: {e})")
            blocks.append("")

        if not args.no_comments:
            blocks.extend(
                top_comments_block(
                    vid,
                    top_n=args.top_comments,
                    max_fetch=args.comment_fetch_max,
                )
            )

        hook = extract_spoken_hook(vid)
        blocks.append("## Hook (first spoken sentence)")
        blocks.append(f'"{hook}"' if hook else "(no speech detected)")
        blocks.append("")

        blocks.append(body)
        blocks.append("")

    blocks.extend(["=" * 80, "END", "=" * 80, ""])
    OUT.write_text("\n".join(blocks), encoding="utf-8")
    print("wrote", OUT, f"({len(files)} videos)")


if __name__ == "__main__":
    main()
