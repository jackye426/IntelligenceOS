"""Whisper segment alignment for same-audio A/B detection."""

from __future__ import annotations

import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from marketing_pipeline import config

# Same underlying Liz audio; hooks differ; not posted same day.
SEGMENT_ALIGN_MIN = 0.73
HOOK_SIM_MAX = 0.92
MIN_POST_GAP_DAYS = 1


def _norm(text: str | None) -> str:
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def text_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def load_whisper_segments(video_id: str, *, transcripts_dir: Path | None = None) -> list[dict]:
    base = transcripts_dir or config.TRANSCRIPTS_DIR
    path = base / f"{video_id}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("segments") or [])


def segment_align_score(segs_a: list[dict], segs_b: list[dict]) -> float:
    """
    Mean of best segment text matches in A against B.
    Same re-cut audio typically scores ≥0.85; unrelated clips stay low.
    """
    if not segs_a or not segs_b:
        return 0.0
    texts_b = [_norm(s.get("text") or "") for s in segs_b]
    scores: list[float] = []
    for sa in segs_a:
        ta = _norm(sa.get("text") or "")
        if len(ta) < 8:
            continue
        best = max((text_similarity(ta, tb) for tb in texts_b if tb), default=0.0)
        scores.append(best)
    if not scores:
        return 0.0
    scores.sort(reverse=True)
    top = scores[: max(3, len(scores) // 2)]
    return sum(top) / len(top)


def post_gap_days(posted_a: str | None, posted_b: str | None) -> int | None:
    def _parse(iso: str | None) -> datetime | None:
        if not iso:
            return None
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            return None

    da, db = _parse(posted_a), _parse(posted_b)
    if not da or not db:
        return None
    return abs((da.date() - db.date()).days)


def ab_posts_on_different_days(posted_a: str | None, posted_b: str | None) -> bool:
    gap = post_gap_days(posted_a, posted_b)
    if gap is None:
        return True
    return gap >= MIN_POST_GAP_DAYS
