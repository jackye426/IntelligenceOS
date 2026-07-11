"""Deterministic Instagram component extraction."""

from __future__ import annotations

import re
from typing import Any

from marketing_pipeline.instagram.models import InstagramComponents, InstagramFormat

CTA_WORDS = (
    "book",
    "dm",
    "comment",
    "save",
    "share",
    "follow",
    "link in bio",
    "ask",
    "download",
)


def first_text_line(text: str | None, *, max_len: int = 180) -> str | None:
    if not text:
        return None
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:max_len]
    return None


def infer_format(raw: dict[str, Any], tracker: dict[str, Any] | None = None) -> InstagramFormat:
    tracker_format = str((tracker or {}).get("format") or "").lower()
    typename = str(raw.get("typename") or "").lower()
    product_type = str(raw.get("product_type") or "").lower()
    if "carousel" in tracker_format or "sidecar" in typename:
        return "carousel"
    if "reel" in tracker_format or product_type == "clips":
        return "reel"
    if raw.get("is_video") or "video" in typename:
        return "reel"
    if "image" in typename or "static" in tracker_format or "photo" in tracker_format:
        return "static"
    return "unknown"


def infer_funnel_stage(text: str | None, topic: str | None = None) -> str:
    haystack = f"{text or ''} {topic or ''}".lower()
    if any(term in haystack for term in ("book", "consult", "appointment", "clinic", "link in bio")):
        return "BOFU"
    if any(term in haystack for term in ("cost", "symptom", "treatment", "diagnosis", "what happens")):
        return "MOFU"
    if any(term in haystack for term in ("did you know", "myth", "signs", "things", "why")):
        return "TOFU"
    return "unclear"


def infer_cta(text: str | None, tracker_cta: str | None = None) -> str | None:
    if tracker_cta:
        return tracker_cta
    if not text:
        return None
    lower = text.lower()
    for word in CTA_WORDS:
        if word in lower:
            return word
    return None


def infer_slide_pattern(text: str | None) -> str | None:
    lower = (text or "").lower()
    if any(term in lower for term in ("myth", "truth", "misconception")):
        return "myth_busting"
    if any(term in lower for term in ("checklist", "things", "signs", "steps")):
        return "checklist"
    if any(term in lower for term in ("before", "after")):
        return "before_after"
    if any(term in lower for term in ("patient", "story", "journey")):
        return "patient_story"
    if any(term in lower for term in ("doctor", "consultant", "surgeon", "explains")):
        return "doctor_explainer"
    return None


def infer_creative_pattern(fmt: InstagramFormat, text: str | None) -> str | None:
    lower = (text or "").lower()
    if "?" in (text or ""):
        return "direct_question"
    if re.search(r"\b\d+\b", lower):
        return "numbered_list"
    if any(term in lower for term in ("pov", "when you", "you might")):
        return "relatable_setup"
    if fmt == "carousel":
        return infer_slide_pattern(text) or "educational_carousel"
    if fmt == "reel":
        return "spoken_or_visual_reel"
    if fmt == "static":
        return "static_explainer"
    return None


def build_components(
    *,
    fmt: InstagramFormat,
    caption: str | None,
    tracker: dict[str, Any] | None,
    child_media: list[dict[str, Any]],
    transcript: str | None = None,
    source_layers: list[str] | None = None,
) -> InstagramComponents:
    tracker = tracker or {}
    cover_hook = tracker.get("hook_cover_text") or first_text_line(caption)
    caption_opening = tracker.get("caption_opening_line") or first_text_line(caption)
    topic = tracker.get("topic")
    cta = infer_cta(caption, tracker.get("cta"))
    slide_pattern = infer_slide_pattern(caption) if fmt == "carousel" else None
    has_watch_metrics = bool((tracker.get("metrics") or {}).get("avg_watch_time_sec"))
    return InstagramComponents(
        format=fmt,
        cover_hook=cover_hook,
        caption_opening=caption_opening,
        topic=topic,
        content_bucket=tracker.get("content_bucket"),
        featured_person=tracker.get("featured_person"),
        cta=cta,
        funnel_stage=infer_funnel_stage(caption, topic),
        creative_pattern=infer_creative_pattern(fmt, caption),
        save_reason="reference_or_checklist" if fmt == "carousel" and slide_pattern else None,
        visual_structure="multi_slide" if fmt == "carousel" else fmt,
        slide_count=len(child_media) or None,
        cover_claim=cover_hook if fmt == "carousel" else None,
        slide_pattern=slide_pattern,
        final_cta=cta if fmt == "carousel" else None,
        saveability="high" if fmt == "carousel" and slide_pattern in {"checklist", "myth_busting"} else None,
        speaker=tracker.get("featured_person") if fmt == "reel" else None,
        audio_type="unknown" if fmt == "reel" else None,
        transcript_status="complete" if transcript else "unavailable",
        opening_line=first_text_line(transcript) if transcript else caption_opening,
        watch_metric_layer="available" if has_watch_metrics else "missing",
        source_layers=source_layers or [],
    )

