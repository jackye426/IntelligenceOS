"""Insight-card classifier. LLM extracts; quote validation drops unsupported claims."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from marketing_pipeline.creators.store import get_store

CLASSIFIER_VERSION = "classify_v1"
HOOK_JOBS = (
    "name_the_problem",
    "contradict_belief",
    "authority_first",
    "curiosity_gap",
    "numbered_promise",
    "patient_situation",
    "myth",
    "other",
)


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    quote: str
    source: str


class InsightCardModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_doctor: bool
    doctor_confidence: float = Field(ge=0, le=1)
    doctor_role: str | None = None
    specialty_raw: str | None = None
    specialty_key: str | None = None
    geo_country: str | None = None
    geo_confidence: float | None = Field(default=None, ge=0, le=1)
    practice_setting: str | None = None
    growth_intent_level: int = Field(ge=0, le=3)
    positioning_line: str | None = None
    named_promise: str | None = None
    who_it_is_for: str | None = None
    hook_jobs: list[str] = Field(default_factory=list)
    content_formats: list[str] = Field(default_factory=list)
    format_mix: dict[str, int] = Field(default_factory=dict)
    cta_types: list[str] = Field(default_factory=list)
    series_markers: list[str] = Field(default_factory=list)
    caption_hooks: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)


def input_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def quote_in_source(quote: str, sources: dict[str, str]) -> bool:
    needle = (quote or "").strip()
    if not needle:
        return False
    return any(needle in body for body in sources.values() if body)


def validate_quotes(
    card: InsightCardModel, sources: dict[str, str]
) -> tuple[InsightCardModel, dict[str, Any]]:
    kept: list[EvidenceItem] = []
    dropped: list[str] = []
    for item in card.evidence:
        src_body = sources.get(item.source, "")
        blob = " ".join(sources.values())
        if item.quote and (item.quote in src_body or item.quote in blob):
            kept.append(item)
        else:
            dropped.append(item.field)
    data = card.model_dump()
    data["evidence"] = [e.model_dump() for e in kept]
    supported = {e.field for e in kept}
    for field in ("is_doctor", "geo_country", "growth_intent_level"):
        if field in dropped or (field not in supported and data.get(field) not in (None, False, 0)):
            # identity fields may be supported by the whole bio even without a tagged quote
            if field == "is_doctor" and data.get("is_doctor"):
                continue
    if "geo_country" in dropped:
        data["geo_country"] = None
        data["geo_confidence"] = None
    if "growth_intent_level" in dropped and "growth_intent_level" not in supported:
        data["growth_intent_level"] = None
    if "is_doctor" in dropped and "is_doctor" not in supported:
        data["is_doctor"] = None
        data["doctor_confidence"] = None
    return InsightCardModel.model_validate(
        {**data, "growth_intent_level": data.get("growth_intent_level") or 0}
    ), {"dropped": dropped, "kept": [e.field for e in kept]}


def heuristic_card(profile: dict[str, Any], videos: list[dict[str, Any]]) -> InsightCardModel:
    """Used in tests and when no LLM key is configured. Still quote-backed."""
    bio = profile.get("bio") or ""
    nick = profile.get("nickname") or ""
    screen = profile.get("screen_result")
    is_doctor = screen == "include"
    quotes = []
    if is_doctor:
        token = next((w for w in ("Dr", "surgeon", "GP", "consultant") if w.lower() in f"{nick} {bio}".lower()), "Dr")
        quotes.append(EvidenceItem(field="is_doctor", quote=token, source="bio" if token.lower() in bio.lower() else "nickname"))
    links = profile.get("bio_links") or []
    classes = {i.get("class") for i in links if isinstance(i, dict)}
    intent = 0
    if "booking_platform" in classes or "own_site" in classes:
        intent = 2
        quotes.append(EvidenceItem(field="growth_intent_level", quote=profile.get("bio_link") or bio[:40], source="bio"))
    geo = profile.get("geo_country")
    if geo:
        quotes.append(EvidenceItem(field="geo_country", quote=geo, source="bio"))
    hooks = [v.get("caption_hook") for v in videos if v.get("caption_hook")]
    return InsightCardModel(
        is_doctor=bool(is_doctor),
        doctor_confidence=0.9 if is_doctor else 0.4,
        doctor_role="doctor" if is_doctor else None,
        specialty_key=profile.get("specialty_key"),
        geo_country=geo,
        geo_confidence=profile.get("geo_confidence"),
        practice_setting=profile.get("practice_setting")
        or ("private" if "own_site" in classes or "booking_platform" in classes else None),
        growth_intent_level=intent,
        positioning_line=None,
        hook_jobs=["other"] if hooks else [],
        content_formats=[],
        cta_types=["link_in_bio"] if profile.get("bio_link") else [],
        caption_hooks=hooks[:8],
        evidence=quotes,
    )


def apply_card(
    profile: dict[str, Any],
    card: InsightCardModel,
    *,
    store=None,
    input_key: str,
    model: str | None = None,
) -> dict[str, Any]:
    store = store or get_store()
    payload = card.model_dump()
    row = store.upsert(
        "creator_insight_cards",
        {
            "creator_profile_id": profile["id"],
            "classifier_version": CLASSIFIER_VERSION,
            "prompt_fingerprint": CLASSIFIER_VERSION,
            "model": model or "heuristic",
            "input_hash": input_key,
            "output": payload,
            "evidence": payload.get("evidence") or [],
            "quote_validation": {},
            "is_doctor": card.is_doctor,
            "doctor_confidence": card.doctor_confidence,
            "doctor_role": card.doctor_role,
            "specialty_raw": card.specialty_raw,
            "specialty_key": card.specialty_key,
            "geo_country": card.geo_country,
            "geo_confidence": card.geo_confidence,
            "practice_setting": card.practice_setting,
            "growth_intent_level": card.growth_intent_level,
            "positioning_line": card.positioning_line,
            "named_promise": card.named_promise,
            "who_it_is_for": card.who_it_is_for,
            "hook_jobs": card.hook_jobs,
            "content_formats": card.content_formats,
            "format_mix": card.format_mix,
            "cta_types": card.cta_types,
            "series_markers": card.series_markers,
            "caption_hooks": card.caption_hooks[:8],
        },
        keys=("creator_profile_id", "classifier_version", "input_hash"),
    )
    identity_lost = card.is_doctor is None or card.geo_country is None or card.growth_intent_level is None
    patch = {
        "insight_card_id": row.get("id"),
        "is_doctor": card.is_doctor,
        "doctor_confidence": card.doctor_confidence,
        "doctor_role": card.doctor_role,
        "specialty_raw": card.specialty_raw,
        "specialty_key": card.specialty_key,
        "geo_country": card.geo_country,
        "geo_confidence": card.geo_confidence,
        "practice_setting": card.practice_setting,
        "growth_intent_level": card.growth_intent_level,
        "positioning_line": card.positioning_line,
        "hook_jobs": card.hook_jobs,
        "format_mix": card.format_mix,
        "cta_mix": {k: 1 for k in card.cta_types},
        "stage": "classified",
        "work_status": "ready",
    }
    if identity_lost:
        patch["lane"] = "pending_review"
    store.update("creator_profiles", patch, id=profile["id"])
    return row


CLASSIFY_SYSTEM = """You extract a structured insight card from a TikTok doctor profile.
Return JSON only matching this schema (extra keys forbidden):
{
  "is_doctor": bool,
  "doctor_confidence": float 0-1,
  "doctor_role": string|null,
  "specialty_raw": string|null,
  "specialty_key": string|null,
  "geo_country": string|null,
  "geo_confidence": float|null,
  "practice_setting": string|null,
  "growth_intent_level": 0|1|2|3,
  "positioning_line": string|null,
  "named_promise": string|null,
  "who_it_is_for": string|null,
  "hook_jobs": [string],
  "content_formats": [string],
  "format_mix": {string: int},
  "cta_types": [string],
  "series_markers": [string],
  "caption_hooks": [string],
  "evidence": [{"field": string, "quote": string, "source": "bio"|"nickname"|"captions"}]
}
Every non-null identity claim (is_doctor, geo_country, growth_intent_level) MUST have a verbatim quote from bio, nickname, or captions.
hook_jobs must be from: name_the_problem, contradict_belief, authority_first, curiosity_gap, numbered_promise, patient_situation, myth, other.
growth_intent: 0 none; 1 brand-building; 2 practice promotion (own site / booking / private practice); 3 explicit book/DM/enquiry CTA.
If you cannot support a field with a quote, set it null / 0 / false.
"""


def _strip_json(text: str) -> str:
    import re

    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _sources(profile: dict[str, Any], videos: list[dict[str, Any]]) -> dict[str, str]:
    captions = "\n".join(
        f"[{v.get('video_id')}] {(v.get('caption') or v.get('caption_hook') or '')[:300]}"
        for v in videos[:23]
    )
    return {
        "bio": profile.get("bio") or "",
        "nickname": profile.get("nickname") or "",
        "captions": captions,
        "bio_link": profile.get("bio_link") or "",
    }


def _sanitize_llm_payload(data: dict[str, Any]) -> dict[str, Any]:
    allowed = set(InsightCardModel.model_fields)
    cleaned = {k: v for k, v in data.items() if k in allowed}
    if cleaned.get("growth_intent_level") is None:
        cleaned["growth_intent_level"] = 0
    if cleaned.get("doctor_confidence") is None:
        cleaned["doctor_confidence"] = 0.0
    hooks = cleaned.get("hook_jobs") or []
    cleaned["hook_jobs"] = [h for h in hooks if h in HOOK_JOBS]
    evidence = []
    for item in cleaned.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        if not item.get("field") or not item.get("quote"):
            continue
        evidence.append(
            {
                "field": item["field"],
                "quote": item["quote"],
                "source": item.get("source") or "bio",
            }
        )
    cleaned["evidence"] = evidence
    return cleaned


def classify_v1_llm(profile: dict[str, Any], videos: list[dict[str, Any]]) -> InsightCardModel:
    from marketing_pipeline import config
    from marketing_pipeline.shared.openrouter_client import chat_completion

    sources = _sources(profile, videos)
    user = json.dumps(
        {
            "nickname": profile.get("nickname"),
            "bio": profile.get("bio"),
            "bio_link": profile.get("bio_link"),
            "bio_links": profile.get("bio_links"),
            "geo_signals": profile.get("geo_signals"),
            "rollups": {
                "follower_count": profile.get("follower_count"),
                "posts_30d": profile.get("posts_30d"),
                "median_saves_per_1k": profile.get("median_saves_per_1k"),
                "median_views": profile.get("median_views"),
            },
            "caption_hooks": [v.get("caption_hook") for v in videos[:23] if v.get("caption_hook")],
            "captions": sources["captions"],
        },
        ensure_ascii=False,
    )
    raw = chat_completion(
        system=CLASSIFY_SYSTEM,
        user=user,
        model=config.MODEL_CREATOR_CLASSIFY,
        max_tokens=2000,
    )
    data = json.loads(_strip_json(raw))
    if not isinstance(data, dict):
        raise ValueError("classifier did not return an object")
    card = InsightCardModel.model_validate(_sanitize_llm_payload(data))
    card, _meta = validate_quotes(card, sources)
    return card


def classify_v1(
    profile: dict[str, Any],
    videos: list[dict[str, Any]],
    *,
    use_llm: bool | None = None,
) -> tuple[InsightCardModel, str]:
    """LLM extract with quote validation; heuristic fallback when no key / LLM fails."""
    from marketing_pipeline import config

    if use_llm is None:
        use_llm = bool(config.OPENROUTER_API_KEY)
    if use_llm:
        try:
            return classify_v1_llm(profile, videos), config.MODEL_CREATOR_CLASSIFY
        except (ValidationError, ValueError, json.JSONDecodeError, RuntimeError):
            pass
    return heuristic_card(profile, videos), "heuristic"

