"""On-screen hook extraction via frame capture + vision OCR."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from marketing_pipeline import config
from marketing_pipeline.shared.vision_ocr import ocr_image
from marketing_pipeline.tiktok.stages.download_media import download_media, resolve_media_path
from marketing_pipeline.tiktok.stages.extract_frames import extract_hook_frames
from marketing_pipeline.tiktok.stages.transcript_utils import is_garbage_transcript

NOISE_RE = re.compile(r"^(@\w+|tiktok|docmap)\s*$", re.I)


def _cache_path(video_id: str) -> Path:
    return config.OCR_CACHE_DIR / f"{video_id}.json"


def _load_cache(video_id: str) -> dict[str, Any] | None:
    path = _cache_path(video_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _save_cache(video_id: str, payload: dict[str, Any]) -> None:
    config.OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(video_id).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _pick_best_text(results: list[dict[str, Any]]) -> tuple[str | None, float]:
    best_text: str | None = None
    best_score = 0.0
    for item in results:
        text = (item.get("text") or "").strip()
        conf = float(item.get("confidence") or 0.0)
        if not text or NOISE_RE.match(text):
            continue
        cleaned = re.sub(r"\s+", " ", text)
        score = conf * 100 + min(len(cleaned), 120)
        if score > best_score:
            best_score = score
            best_text = cleaned[:300]
    return best_text, best_score


def run_ocr_for_video(
    video_id: str,
    *,
    transcript: str | None = None,
    caption: str | None = None,
    download_if_missing: bool = True,
    force_refresh: bool = False,
) -> dict[str, Any]:
    if not force_refresh:
        cached = _load_cache(video_id)
        if cached and cached.get("onscreen_hook"):
            return cached

    carousel = is_garbage_transcript(transcript, caption_hint=caption)
    media = resolve_media_path(video_id)
    if media is None and download_if_missing:
        try:
            media = download_media(video_id)
        except Exception as exc:  # noqa: BLE001
            payload = {
                "video_id": video_id,
                "onscreen_hook": None,
                "confidence": 0.0,
                "format_guess": "carousel" if carousel else "video",
                "error": str(exc),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            _save_cache(video_id, payload)
            return payload

    if media is None:
        return {
            "video_id": video_id,
            "onscreen_hook": None,
            "confidence": 0.0,
            "format_guess": "carousel" if carousel else "video",
            "error": "no_media",
        }

    frames = extract_hook_frames(video_id, media, carousel=carousel)
    ocr_results: list[dict[str, Any]] = []
    for frame in frames:
        try:
            result = ocr_image(frame)
            result["frame"] = frame.name
            ocr_results.append(result)
        except Exception as exc:  # noqa: BLE001
            ocr_results.append({"frame": frame.name, "text": "", "confidence": 0.0, "error": str(exc)})

    hook_text, score = _pick_best_text(ocr_results)
    payload = {
        "video_id": video_id,
        "onscreen_hook": hook_text,
        "confidence": round(min(score / 100, 1.0), 2) if hook_text else 0.0,
        "format_guess": "carousel" if carousel else "video",
        "frames": [str(f) for f in frames],
        "ocr_results": ocr_results,
        "model": config.MODEL_OCR,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_cache(video_id, payload)
    return payload


def extract_onscreen_hook(
    video_id: str,
    *,
    transcript: str | None = None,
    caption: str | None = None,
    media_dir: Path | None = None,
    force_refresh: bool = False,
) -> str | None:
    _ = media_dir
    cached = _load_cache(video_id)
    if cached and not force_refresh:
        return cached.get("onscreen_hook")

    if force_refresh or not cached:
        result = run_ocr_for_video(
            video_id,
            transcript=transcript,
            caption=caption,
            download_if_missing=False,
            force_refresh=force_refresh,
        )
        return result.get("onscreen_hook")
    return cached.get("onscreen_hook")
