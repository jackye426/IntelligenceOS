"""LLM carousel copy generation with template selection."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from common.openrouter_client import chat_completion
from carousel.pptx_builder import CarouselContent, get_template, load_templates

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


class SlideCopy(BaseModel):
    main_text: str
    subtext: str = ""


class CarouselDraftResponse(BaseModel):
    template_id: str
    template_reason: str = ""
    topic: str
    hook: str
    hook_subtitle: str = ""
    slides: list[SlideCopy] = Field(min_length=3, max_length=12)
    cta: str
    caption: str


def _template_catalog_for_prompt() -> str:
    lines = []
    for t in load_templates():
        best = ", ".join(t.get("best_for") or [])
        lines.append(
            f"- {t['id']}: {t['name']} — {t.get('description', '')} (best for: {best})"
        )
    return "\n".join(lines)


def _parse_json_response(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    m = _JSON_FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    # Find first { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def _build_system_prompt() -> str:
    return (
        "You write Instagram carousel copy for DocMap (UK endometriosis / women's health).\n"
        "Return ONLY valid JSON matching the schema. No markdown fences.\n\n"
        "Rules:\n"
        "- UK/NHS tone: calm, validating, practical. No fear-mongering.\n"
        "- Pick exactly one template_id from the catalog that fits the content shape.\n"
        "- hook: punchy opener (max ~12 words if possible).\n"
        "- hook_subtitle: optional supporting line (max ~10 words); empty string if not needed.\n"
        "- slides: 5-8 body slides. Each slide has main_text (headline, short) and subtext (1-2 sentences max).\n"
        "- Keep copy concise — text will be auto-sized into fixed boxes; shorter is better.\n"
        "- main_text: aim for ≤8 words. subtext: aim for ≤25 words.\n"
        "- cta: one clear next step (save, share, link in bio).\n"
        "- caption: Instagram caption with line breaks; include 3-5 relevant hashtags at end.\n\n"
        "Template catalog:\n"
        f"{_template_catalog_for_prompt()}\n\n"
        "JSON schema:\n"
        "{\n"
        '  "template_id": "classic_blue|photo_center_hook|photo_body_left|photo_body_right|minimal_white",\n'
        '  "template_reason": "why this template",\n'
        '  "topic": "short topic label",\n'
        '  "hook": "...",\n'
        '  "hook_subtitle": "...",\n'
        '  "slides": [{"main_text": "...", "subtext": "..."}],\n'
        '  "cta": "...",\n'
        '  "caption": "..."\n'
        "}"
    )


def generate_carousel_copy(
    *,
    topic: str,
    angle: str | None = None,
    context: str | None = None,
    template_id: str | None = None,
    slide_count: int = 6,
    audience_notes: str | None = None,
) -> CarouselDraftResponse:
    if template_id:
        get_template(template_id)  # validate early

    user_parts = [f"Topic: {topic}"]
    if angle:
        user_parts.append(f"Angle: {angle}")
    if audience_notes:
        user_parts.append(f"Audience: {audience_notes}")
    if context:
        user_parts.append(f"Context / source material:\n{context[:6000]}")
    if template_id:
        user_parts.append(f"Use template_id: {template_id} (do not pick another).")
    else:
        user_parts.append("Pick the best template_id for this content.")
    user_parts.append(f"Target body slide count: {slide_count} (not counting hook/cta).")

    raw = chat_completion(
        system=_build_system_prompt(),
        user="\n\n".join(user_parts),
        max_tokens=2500,
    )
    try:
        data = _parse_json_response(raw)
        draft = CarouselDraftResponse.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise RuntimeError(f"Carousel writer returned invalid JSON: {exc}\nRaw: {raw[:800]}") from exc

    if template_id:
        draft.template_id = template_id
    else:
        get_template(draft.template_id)  # validate LLM pick

    return draft


def draft_to_content(draft: CarouselDraftResponse) -> CarouselContent:
    return CarouselContent(
        topic=draft.topic,
        template_id=draft.template_id,
        hook=draft.hook,
        hook_subtitle=draft.hook_subtitle or None,
        slides=[{"main_text": s.main_text, "subtext": s.subtext} for s in draft.slides],
        cta=draft.cta,
        caption=draft.caption,
    )
