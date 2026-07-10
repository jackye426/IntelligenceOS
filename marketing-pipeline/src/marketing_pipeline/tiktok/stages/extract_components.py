"""Batch-extract structured video components (hooks-first schema)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from marketing_pipeline import config
from marketing_pipeline.shared.openrouter_client import chat_completion
from marketing_pipeline.tiktok.models import TikTokMarketingDataset, TikTokVideoRecord
from marketing_pipeline.tiktok.stages.extract_hooks import resolve_primary_hook
from marketing_pipeline.tiktok.stages.video_components_models import (
    HOOK_TYPE_VALUES,
    VideoComponents,
)
from marketing_pipeline.tiktok.stages.video_components_store import (
    load_components,
    rebuild_index,
    save_components,
)
from marketing_pipeline.tiktok.sync.supabase import load_dataset

SYSTEM_PROMPT = """You extract structured marketing components from DocMap TikTok videos
(endometriosis patient education / specialist access).

Return ONLY valid JSON matching the schema. No markdown fences.

Rules:
- Classify hook.type using ONLY this vocabulary:
  myth_correction, warning, direct_question, symptom_recognition, unexpected_fact,
  authority_statement, personal_story, list_promise, outcome_promise, contrarian_claim, other
  If other, set type_other to a short phrase.
- hook.channel: spoken | onscreen | both | caption_only
- funnel_stage: TOFU | MOFU | BOFU | unclear
  TOFU = awareness/myths/broad education; MOFU = diagnosis/treatment/specialist explainers;
  BOFU = booking/clinic choice/consult prep/named service.
- CTA: if none, present=false, position=none, channel=none, explicitness=none.
  present may be true, false, or "unclear".
- caption_analysis must be null (deferred).
- Keep quotes short. Prefer the provided primary hook text for hook.text when sensible.
- seconds_to_main_claim: estimate from segment timings when possible, else null.
"""


def _inputs_hash(
    *,
    transcript: str,
    hook_detail: dict[str, Any],
    caption: str | None,
    duration_sec: int | None,
) -> str:
    payload = json.dumps(
        {
            "transcript": transcript.strip(),
            "hook": hook_detail,
            "caption": (caption or "").strip(),
            "duration_sec": duration_sec,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _strip_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _segment_excerpt(segments: list[dict[str, Any]], *, max_chars: int = 2500) -> str:
    lines: list[str] = []
    for seg in segments[:40]:
        start = seg.get("start")
        end = seg.get("end")
        t = (seg.get("text") or "").strip()
        if not t:
            continue
        lines.append(f"[{start:.1f}-{end:.1f}] {t}" if isinstance(start, (int, float)) else t)
    text = "\n".join(lines)
    return text[:max_chars]


def build_user_prompt(video_id: str, rec: TikTokVideoRecord) -> str:
    hook = rec.hook
    primary = resolve_primary_hook(hook) or ""
    segments = rec.transcript.segments or []
    transcript = (rec.transcript.full_text or "")[:4000]
    return f"""video_id: {video_id}
duration_sec: {rec.post.duration_sec or rec.post.metrics.duration_sec}
format_guess: {rec.post.format_guess}
caption: {(rec.post.caption or "")[:800]}

primary_hook: {primary}
spoken_hook: {hook.spoken_hook}
onscreen_hook: {hook.onscreen_hook}
caption_hook: {hook.caption_hook}
hook_source: {hook.hook_source}

transcript:
{transcript}

timed_segments (optional):
{_segment_excerpt(segments)}

Return JSON with keys:
video_id, length_sec, hook, main_claim, supporting_explanation, funnel_stage,
funnel_rationale, cta, topic, speaker, format_raw, caption_analysis, extraction
where extraction may omit method/inputs_hash/extracted_at (filled by pipeline).
hook must include: text, channel, type, type_other, emotional_mechanism_raw,
specificity, target_audience_raw, creates_curiosity, contradicts_common_belief,
payoff_clear, seconds_to_main_claim, window_sec_hint
cta must include: present, wording, position, channel, explicitness,
requested_action_raw, value_exchange_raw, urgency, funnel_stage
topic: primary_raw, secondary_raw
speaker: primary_raw, type_raw
caption_analysis: null
"""


def _as_block(value: Any, *, text_key: str = "text") -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return {text_key: value}
    return {text_key: ""}


def _normalize_llm_payload(data: dict[str, Any], *, video_id: str, duration: int | None) -> dict[str, Any]:
    data = dict(data)
    data["video_id"] = video_id
    data["length_sec"] = duration
    data["caption_analysis"] = None

    hook = data.get("hook")
    if isinstance(hook, str):
        data["hook"] = {"text": hook, "type": "other", "type_other": "unspecified", "channel": "spoken"}
    elif not isinstance(hook, dict):
        data["hook"] = {"text": "", "type": "other", "type_other": "unspecified", "channel": "spoken"}

    if data["hook"].get("type") not in HOOK_TYPE_VALUES:
        data["hook"]["type_other"] = str(data["hook"].get("type_other") or data["hook"].get("type") or "unspecified")
        data["hook"]["type"] = "other"

    claim = _as_block(data.get("main_claim"), text_key="text")
    if "summary" in claim and "text" not in claim:
        claim["text"] = claim.pop("summary")
    data["main_claim"] = claim

    expl = _as_block(data.get("supporting_explanation"), text_key="summary")
    if "text" in expl and "summary" not in expl:
        expl["summary"] = expl.pop("text")
    data["supporting_explanation"] = expl

    cta = data.get("cta")
    if not isinstance(cta, dict):
        data["cta"] = {"present": False, "position": "none", "channel": "none", "explicitness": "none"}
    topic = data.get("topic")
    if isinstance(topic, str):
        data["topic"] = {"primary_raw": topic, "secondary_raw": []}
    elif not isinstance(topic, dict):
        data["topic"] = {"primary_raw": None, "secondary_raw": []}
    speaker = data.get("speaker")
    if isinstance(speaker, str):
        data["speaker"] = {"primary_raw": speaker, "type_raw": None}
    elif not isinstance(speaker, dict):
        data["speaker"] = {"primary_raw": None, "type_raw": None}
    return data


def extract_one(
    video_id: str,
    rec: TikTokVideoRecord,
    *,
    force: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    transcript = (rec.transcript.full_text or "").strip()
    if not transcript:
        return {"video_id": video_id, "status": "skipped", "reason": "no_transcript"}

    hook_detail = rec.hook.model_dump()
    duration = rec.post.duration_sec or rec.post.metrics.duration_sec
    digest = _inputs_hash(
        transcript=transcript,
        hook_detail=hook_detail,
        caption=rec.post.caption,
        duration_sec=duration,
    )

    existing = load_components(video_id)
    if existing and not force and existing.extraction.inputs_hash == digest:
        return {"video_id": video_id, "status": "skipped", "reason": "unchanged_hash"}

    used_model = model or config.MODEL_COMPONENTS
    raw = chat_completion(
        system=SYSTEM_PROMPT,
        user=build_user_prompt(video_id, rec),
        model=used_model,
        max_tokens=2200,
    )
    data = _normalize_llm_payload(json.loads(_strip_json(raw)), video_id=video_id, duration=duration)

    extraction = data.get("extraction") if isinstance(data.get("extraction"), dict) else {}
    extraction.update(
        {
            "method": "batch_llm_v1",
            "model": used_model,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "inputs_hash": digest,
            "confidence": float(extraction.get("confidence") or 0.6),
            "needs_review": bool(extraction.get("needs_review") or False),
        }
    )
    if not (data.get("main_claim") or {}).get("text"):
        extraction["needs_review"] = True
    if data.get("funnel_stage") == "unclear":
        extraction["needs_review"] = True
    data["extraction"] = extraction

    primary = resolve_primary_hook(rec.hook)
    if primary and isinstance(data.get("hook"), dict) and not data["hook"].get("text"):
        data["hook"]["text"] = primary

    card = VideoComponents.model_validate(data)
    save_components(card)
    return {
        "video_id": video_id,
        "status": "extracted",
        "hook_type": card.hook.type,
        "funnel_stage": card.funnel_stage,
        "cta_present": card.cta.present,
        "needs_review": card.extraction.needs_review,
    }


def run_extract_components(
    *,
    video_id: str | None = None,
    force: bool = False,
    limit: int | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    dataset: TikTokMarketingDataset = load_dataset()
    ids = [video_id] if video_id else sorted(dataset.videos.keys())
    if limit is not None:
        ids = ids[:limit]

    results: list[dict[str, Any]] = []
    for vid in ids:
        rec = dataset.videos.get(vid)
        if not rec:
            results.append({"video_id": vid, "status": "skipped", "reason": "not_in_dataset"})
            continue
        try:
            results.append(extract_one(vid, rec, force=force, model=model))
        except Exception as exc:  # noqa: BLE001
            results.append({"video_id": vid, "status": "error", "error": str(exc)})

    index = rebuild_index()
    extracted = sum(1 for r in results if r.get("status") == "extracted")
    skipped = sum(1 for r in results if r.get("status") == "skipped")
    errors = sum(1 for r in results if r.get("status") == "error")
    return {
        "processed": len(results),
        "extracted": extracted,
        "skipped": skipped,
        "errors": errors,
        "index_count": index.get("count"),
        "results": results,
    }
