#!/usr/bin/env python3
"""
Score all video pairs using multiple independent signals — not just transcript text.

Outputs a ranked table you can manually verify. Each signal is shown separately so
one weak Whisper run doesn't dominate the verdict.

Signals:
  - segment_align: Whisper segment text overlap (same audio = high)
  - word_jaccard: 5-word-shingle Jaccard on normalized transcript
  - lcs_ratio: longest common substring / shorter transcript length
  - caption_sim: caption first-line similarity
  - hook_diff: on-screen hooks differ (required for A/B, not duplicate)
  - duration_delta: absolute seconds between videos
  - post_gap_days: days between publish dates (reposts often cluster)
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "marketing-pipeline" / "src"))

from marketing_pipeline.tiktok.orchestrator import build_dataset  # noqa: E402


def _norm(text: str | None) -> str:
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _shingles(text: str, n: int = 5) -> set[str]:
    words = _norm(text).split()
    if len(words) < n:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: str, b: str, n: int = 5) -> float:
    sa, sb = _shingles(a, n), _shingles(b, n)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def seq_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def lcs_ratio(a: str, b: str) -> float:
    """Longest common substring length / min transcript length."""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    # O(n*m) DP — fine for ~2k char transcripts
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            best = max(best, k)
    return best / min(len(a), len(b))


from marketing_pipeline.tiktok.stages.segment_align import (
    MIN_POST_GAP_DAYS,
    load_whisper_segments,
    post_gap_days,
    segment_align_score,
    text_similarity as seq_ratio,
)


@dataclass
class PairScore:
    vid_a: str
    vid_b: str
    segment_align: float
    word_jaccard: float
    lcs_ratio: float
    caption_sim: float
    hook_sim: float
    duration_delta: int | None
    post_gap_days: int | None
    composite: float
    signals_hit: int
    views_a: int
    views_b: int
    hook_a: str
    hook_b: str

    def verdict_band(self) -> str:
        if self.composite >= 0.55 and self.signals_hit >= 3 and self.hook_sim < 0.92:
            return "likely_ab"
        if self.composite >= 0.40 and self.signals_hit >= 2:
            return "review"
        if self.composite >= 0.30:
            return "weak"
        return "unlikely"


def score_pair(
    vid_a: str,
    vid_b: str,
    *,
    transcript_a: str,
    transcript_b: str,
    caption_a: str,
    caption_b: str,
    hook_a: str,
    hook_b: str,
    duration_a: int | None,
    duration_b: int | None,
    posted_a: str | None,
    posted_b: str | None,
    views_a: int,
    views_b: int,
) -> PairScore:
    segs_a = load_whisper_segments(vid_a)
    segs_b = load_whisper_segments(vid_b)

    seg = segment_align_score(segs_a, segs_b)
    jac = jaccard(transcript_a, transcript_b)
    lcs = lcs_ratio(transcript_a, transcript_b)
    cap = seq_ratio((caption_a or "").split("\n")[0], (caption_b or "").split("\n")[0])
    hook = seq_ratio(hook_a, hook_b)

    dur_delta = None
    if duration_a is not None and duration_b is not None:
        dur_delta = abs(duration_a - duration_b)

    gap = post_gap_days(posted_a, posted_b)
    if gap is not None and gap < MIN_POST_GAP_DAYS:
        return PairScore(
            vid_a=vid_a,
            vid_b=vid_b,
            segment_align=0.0,
            word_jaccard=0.0,
            lcs_ratio=0.0,
            caption_sim=0.0,
            hook_sim=1.0,
            duration_delta=dur_delta,
            post_gap_days=gap,
            composite=0.0,
            signals_hit=0,
            views_a=views_a,
            views_b=views_b,
            hook_a=hook_a[:70],
            hook_b=hook_b[:70],
        )

    # Independent signal hits (each must clear its own threshold)
    hits = 0
    if seg >= 0.70:
        hits += 1
    if jac >= 0.25:
        hits += 1
    if lcs >= 0.35:
        hits += 1
    if cap >= 0.65:
        hits += 1
    if dur_delta is not None and dur_delta <= 8:
        hits += 1

    # Composite: segment alignment is strongest evidence of same audio
    composite = (
        0.35 * seg
        + 0.25 * jac
        + 0.15 * lcs
        + 0.15 * cap
        + 0.10 * (1.0 if dur_delta is not None and dur_delta <= 8 else 0.0)
    )

    return PairScore(
        vid_a=vid_a,
        vid_b=vid_b,
        segment_align=round(seg, 3),
        word_jaccard=round(jac, 3),
        lcs_ratio=round(lcs, 3),
        caption_sim=round(cap, 3),
        hook_sim=round(hook, 3),
        duration_delta=dur_delta,
        post_gap_days=gap,
        composite=round(composite, 3),
        signals_hit=hits,
        views_a=views_a,
        views_b=views_b,
        hook_a=hook_a[:70],
        hook_b=hook_b[:70],
    )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ds = build_dataset()

    rows: list[PairScore] = []
    vids = list(ds.videos.keys())
    for i, va in enumerate(vids):
        ra = ds.videos[va]
        for vb in vids[i + 1 :]:
            rb = ds.videos[vb]
            hook_a = ra.hook.onscreen_hook or ra.hook.spoken_hook or ""
            hook_b = rb.hook.onscreen_hook or rb.hook.spoken_hook or ""
            if not hook_a or not hook_b:
                continue
            # Skip near-duplicate hooks (re-uploads, not A/B tests)
            if seq_ratio(hook_a, hook_b) > 0.95:
                continue

            ps = score_pair(
                va,
                vb,
                transcript_a=ra.transcript.full_text or "",
                transcript_b=rb.transcript.full_text or "",
                caption_a=ra.post.caption or "",
                caption_b=rb.post.caption or "",
                hook_a=hook_a,
                hook_b=hook_b,
                duration_a=ra.post.duration_sec,
                duration_b=rb.post.duration_sec,
                posted_a=ra.post.posted_at,
                posted_b=rb.post.posted_at,
                views_a=ra.post.metrics.views or 0,
                views_b=rb.post.metrics.views or 0,
            )
            if ps.composite >= 0.28 or ps.signals_hit >= 2:
                rows.append(ps)

    rows.sort(key=lambda r: (-r.composite, -r.signals_hit))

    out_path = ROOT / "marketing-pipeline" / "tiktok" / "data" / "analysis" / "ab_pair_multisignal.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps([r.__dict__ for r in rows], indent=2),
        encoding="utf-8",
    )

    bands = {"likely_ab": [], "review": [], "weak": []}
    for r in rows:
        b = r.verdict_band()
        if b in bands:
            bands[b].append(r)

    print(f"Videos: {len(vids)}  |  Candidate pairs (composite≥0.28 or ≥2 signals): {len(rows)}")
    print(f"Written: {out_path}\n")

    for band, label in [
        ("likely_ab", "LIKELY A/B (composite≥0.55, ≥3 signals, hooks differ)"),
        ("review", "REVIEW (composite≥0.40, ≥2 signals)"),
        ("weak", "WEAK (composite≥0.30)"),
    ]:
        items = bands[band]
        if not items:
            continue
        print("=" * 72)
        print(label, f"— {len(items)} pairs")
        print("=" * 72)
        for r in items[:20]:
            print(
                f"\n{r.vid_a[-8:]} vs {r.vid_b[-8:]}  "
                f"composite={r.composite}  signals={r.signals_hit}/5  [{band}]"
            )
            print(
                f"  seg={r.segment_align}  jaccard={r.word_jaccard}  lcs={r.lcs_ratio}  "
                f"cap={r.caption_sim}  hook_sim={r.hook_sim}  "
                f"dur_Δ={r.duration_delta}s  post_gap={r.post_gap_days}d"
            )
            print(f"  views: {r.views_a:,} vs {r.views_b:,}")
            print(f"  A: {r.hook_a}")
            print(f"  B: {r.hook_b}")


if __name__ == "__main__":
    main()
