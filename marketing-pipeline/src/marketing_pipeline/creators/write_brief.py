"""content_guidelines_v1 writer: deterministic tests + schema gate.

The LLM write is a later step. This module refuses low yield and invented first-15s n.
"""

from __future__ import annotations

import re
from typing import Any

GUIDELINES_SCHEMA = "content_guidelines_v1"
REQUIRED_SECTIONS = [str(i) for i in range(13)]  # "0" .. "12"
OCR_FRAME_SECONDS = (0.0, 0.5, 1.0, 2.0)

ABSTRACT_WORDS = {
    "journey",
    "wellness",
    "empowerment",
    "healing",
    "hope",
    "transformation",
    "potential",
    "support",
    "advocacy",
    "flourish",
}

YOU_RE = re.compile(r"\b(you|your)\b", re.I)
SENTENCE_RE = re.compile(r"[^.!?]+[.!?]?")


class BriefRefused(RuntimeError):
    def __init__(self, reason: str, coverage: dict[str, Any]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.coverage = coverage


def coverage_from_sample(sample: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(sample)
    transcripts = sum(1 for p in sample if p.get("transcript"))
    timed = sum(1 for p in sample if _timed_transcript(p))
    components = sum(1 for p in sample if p.get("components"))
    ocr = sum(1 for p in sample if p.get("ocr_frames"))
    return {
        "sample_n": n,
        "transcript_yield": (transcripts / n) if n else 0.0,
        "timed_transcript_n": timed,
        "component_yield": (components / n) if n else 0.0,
        "ocr_frame_yield": (ocr / n) if n else 0.0,
        "catalog_n": None,
    }


def _timed_transcript(post: dict[str, Any]) -> list[dict[str, Any]] | None:
    segs = post.get("transcript_segments") or post.get("timed_transcript")
    if isinstance(segs, list) and segs:
        return segs
    return None


def _words_in_first_s(segments: list[dict[str, Any]], limit_s: float = 15.0) -> list[str]:
    words: list[str] = []
    for seg in segments:
        start = float(seg.get("start") or seg.get("start_s") or 0)
        if start >= limit_s:
            continue
        text = str(seg.get("text") or seg.get("word") or "")
        words.extend(w for w in re.findall(r"[A-Za-z']+", text) if w)
    return words


def first15_stats(posts: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for post in posts:
        segs = _timed_transcript(post)
        if not segs:
            continue
        words = _words_in_first_s(segs)
        if not words:
            continue
        text = " ".join(words)
        sentences = [s.strip() for s in SENTENCE_RE.findall(text) if s.strip()]
        you_at = None
        t = 0.0
        for seg in segs:
            start = float(seg.get("start") or 0)
            if start >= 15:
                break
            if YOU_RE.search(str(seg.get("text") or "")):
                you_at = start
                break
            t = start
        abstract = sum(1 for w in words if w.lower() in ABSTRACT_WORDS)
        per_100 = (abstract / len(words)) * 100 if words else 0
        duration = min(15.0, float(posts and 15))
        wps = len(words) / 15.0
        rows.append(
            {
                "video_id": post.get("video_id"),
                "abstract_per_100": per_100,
                "words": len(words),
                "wps": wps,
                "sentences": len(sentences) or 1,
                "words_per_sentence": len(words) / (len(sentences) or 1),
                "seconds_to_you": you_at if you_at is not None else None,
                "ratio": post.get("rolling_local_ratio"),
            }
        )
    winners = [r for r in rows if (r.get("ratio") or 0) >= 2]
    losers = [r for r in rows if r.get("ratio") is not None and r["ratio"] < 1]
    status = "measured" if len(winners) >= 8 and len(losers) >= 8 else "insufficient_sample"
    def avg(items: list[dict[str, Any]], key: str) -> float | None:
        vals = [i[key] for i in items if i.get(key) is not None]
        if not vals:
            return None
        return sum(vals) / len(vals)

    table = None
    if status == "measured":
        keys = (
            "abstract_per_100",
            "words",
            "wps",
            "sentences",
            "words_per_sentence",
            "seconds_to_you",
        )
        table = {
            k: {"top": avg(winners, k), "bottom": avg(losers, k)} for k in keys
        }
    return {
        "status": status,
        "first15_n_top": len(winners),
        "first15_n_bottom": len(losers),
        "table": table,
        "epistemic": "measured" if status == "measured" else "insufficient_sample",
    }


def caption_transcript_ratio(post: dict[str, Any]) -> float | None:
    cap = post.get("caption") or ""
    tr = post.get("transcript") or ""
    if not cap or not tr:
        return None
    return len(cap) / len(tr)


def ocr_banner_static(frames: list[str] | None) -> bool | None:
    if not frames or len(frames) < 4:
        return None
    cleaned = [re.sub(r"\s+", " ", f).strip() for f in frames]
    if any(len(f) < 8 for f in cleaned):
        return False
    return len(set(cleaned)) == 1


def validate_artefact(artefact: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if artefact.get("schema_version") != GUIDELINES_SCHEMA:
        errors.append("schema_version")
    sections = artefact.get("sections") or {}
    for key in REQUIRED_SECTIONS:
        if key not in sections:
            errors.append(f"missing_section_{key}")
    tests = artefact.get("tests") or {}
    first15 = tests.get("first15") or {}
    if first15.get("status") == "insufficient_sample" and first15.get("table"):
        errors.append("invented_first15_table")
    return errors


def refuse_if_low_yield(coverage: dict[str, Any]) -> None:
    if float(coverage.get("transcript_yield") or 0) < 0.70:
        raise BriefRefused("transcript_yield_below_0.70", coverage)
    if float(coverage.get("component_yield") or 0) < 0.70:
        raise BriefRefused("component_yield_below_0.70", coverage)


def build_draft_artefact(
    *,
    handle: str,
    sample: list[dict[str, Any]],
    catalog_n: int,
    ocr_skipped: bool = False,
) -> dict[str, Any]:
    coverage = coverage_from_sample(sample)
    coverage["catalog_n"] = catalog_n
    refuse_if_low_yield(coverage)
    first15 = first15_stats(sample)
    coverage["first15_n_top"] = first15["first15_n_top"]
    coverage["first15_n_bottom"] = first15["first15_n_bottom"]
    ratios = [caption_transcript_ratio(p) for p in sample]
    ratios = [r for r in ratios if r is not None]
    banners = [ocr_banner_static(p.get("ocr_frames")) for p in sample]
    sections = {
        "0": {"title": "one_line_thesis", "body": None, "epistemic": "inferred"},
        "1": {
            "title": "first_15_seconds",
            "table": first15["table"],
            "epistemic": first15["epistemic"],
        },
        "2": {"title": "full_video_structure", "beats": [], "epistemic": "inferred"},
        "3": {
            "title": "production_spec",
            "static_banner_share": sum(1 for b in banners if b) / len(banners) if banners else None,
            "epistemic": "inferred" if ocr_skipped else "measured",
            "ocr_scope": "0,0.5,1.0,2.0s",
        },
        "4": {"title": "length", "epistemic": "measured"},
        "5": {
            "title": "caption_spec",
            "caption_to_transcript_ratio_median": sorted(ratios)[len(ratios) // 2] if ratios else None,
            "epistemic": "measured" if ratios else "inferred",
        },
        "6": {"title": "hook_naming_formulas", "epistemic": "inferred"},
        "7": {"title": "metric_before_format", "epistemic": "measured"},
        "8": {"title": "cadence_and_compounding", "epistemic": "measured"},
        "9": {"title": "anti_patterns", "epistemic": "measured"},
        "10": {"title": "what_not_to_copy", "epistemic": "inferred"},
        "11": {"title": "pre_publish_checklist", "items": []},
        "12": {"title": "how_to_measure_ourselves", "epistemic": "measured"},
    }
    artefact = {
        "schema_version": GUIDELINES_SCHEMA,
        "account_handle": handle,
        "sections": sections,
        "tests": {"first15": first15},
        "coverage": coverage,
    }
    errors = validate_artefact(artefact)
    if errors:
        raise BriefRefused(",".join(errors), coverage)
    return artefact
