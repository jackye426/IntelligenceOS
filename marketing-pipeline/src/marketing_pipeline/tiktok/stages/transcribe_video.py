"""Whisper transcription for TikTok videos."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from marketing_pipeline import config
from marketing_pipeline.tiktok.stages.download_media import download_media, resolve_media_path
from marketing_pipeline.tiktok.stages.transcript_utils import is_garbage_transcript
from marketing_pipeline.tiktok.stages.write_per_video_complete import write_complete_transcript

# Reuse a single WhisperModel per model_id for the process lifetime. Creating a
# new model per video causes memory churn (each instance loads weights + spawns
# CTranslate2 threads) which OOM-kills the worker on batch transcription.
_MODEL_CACHE: dict[str, Any] = {}


def _get_model(model_id: str) -> Any:
    model = _MODEL_CACHE.get(model_id)
    if model is None:
        from faster_whisper import WhisperModel

        model = WhisperModel(
            model_id,
            device="cpu",
            compute_type="int8",
            cpu_threads=config.WHISPER_CPU_THREADS,
        )
        _MODEL_CACHE[model_id] = model
    return model


def _remove_transcript_artifacts(video_id: str, *, out_dir: Path) -> None:
    for name in (f"{video_id}.json", f"{video_id}.txt", f"{video_id}_FULL.txt", f"{video_id}_COMPLETE.txt"):
        path = out_dir / name
        if path.exists():
            path.unlink()


def transcribe_media(
    media_path: Path,
    video_id: str,
    *,
    model_size: str | None = None,
    caption_hint: str | None = None,
    out_dir: Path | None = None,
) -> tuple[list[dict], str]:
    target = out_dir or config.TRANSCRIPTS_DIR
    target.mkdir(parents=True, exist_ok=True)
    model_id = model_size or config.WHISPER_MODEL
    model = _get_model(model_id)
    segments, info = model.transcribe(
        str(media_path),
        language="en",
        beam_size=5,
        condition_on_previous_text=True,
        vad_filter=False,
    )
    rows = [
        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
        for s in segments
    ]
    full_text = " ".join(r["text"] for r in rows if r["text"]).strip()
    if is_garbage_transcript(full_text, caption_hint=caption_hint):
        _remove_transcript_artifacts(video_id, out_dir=target)
        return [], ""

    payload = {
        "video_id": video_id,
        "source_media": media_path.name,
        "whisper_model": model_id,
        "model": model_id,
        "language": getattr(info, "language", None),
        "duration_after_vad": getattr(info, "duration", None),
        "full_text": full_text,
        "segments": rows,
    }
    (target / f"{video_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [f"[{r['start']:.1f}-{r['end']:.1f}] {r['text']}" for r in rows]
    (target / f"{video_id}.txt").write_text("\n".join(lines), encoding="utf-8")
    (target / f"{video_id}_FULL.txt").write_text(full_text + ("\n" if full_text else ""), encoding="utf-8")
    return rows, full_text


def transcribe_video(
    video_id: str,
    meta: dict,
    *,
    model_size: str | None = None,
    download_if_missing: bool = True,
    out_dir: Path | None = None,
) -> dict:
    """Download (if needed), transcribe, and write COMPLETE file. Returns status dict."""
    target = out_dir or config.TRANSCRIPTS_DIR
    media = resolve_media_path(video_id)
    if media is None and download_if_missing:
        try:
            media = download_media(video_id)
        except Exception as exc:  # noqa: BLE001
            return {"video_id": video_id, "status": "download_failed", "error": str(exc)}

    if media is None:
        return {"video_id": video_id, "status": "no_media"}

    try:
        _rows, full_text = transcribe_media(
            media,
            video_id,
            model_size=model_size,
            caption_hint=meta.get("description"),
            out_dir=target,
        )
    except Exception as exc:  # noqa: BLE001
        return {"video_id": video_id, "status": "transcribe_error", "error": str(exc)}

    if not full_text.strip():
        return {"video_id": video_id, "status": "skipped_carousel_or_no_speech"}

    write_complete_transcript(
        video_id,
        full_text,
        title=meta.get("title"),
        description=meta.get("description"),
        webpage_url=meta.get("webpage_url"),
        out_dir=target,
    )
    return {"video_id": video_id, "status": "transcribed", "chars": len(full_text)}
