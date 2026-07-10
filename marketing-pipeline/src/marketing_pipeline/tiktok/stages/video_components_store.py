"""Sidecar + index I/O for video component cards."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from marketing_pipeline import config
from marketing_pipeline.tiktok.stages.video_components_models import VideoComponents

COMPONENTS_DIR = config.ANALYSIS_DIR / "video_components"
INDEX_PATH = config.ANALYSIS_DIR / "video_components_index.json"


def components_dir() -> Path:
    COMPONENTS_DIR.mkdir(parents=True, exist_ok=True)
    return COMPONENTS_DIR


def sidecar_path(video_id: str) -> Path:
    return components_dir() / f"{video_id}.json"


def load_components(video_id: str) -> VideoComponents | None:
    path = sidecar_path(video_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return VideoComponents.model_validate(data)


def save_components(card: VideoComponents) -> Path:
    path = sidecar_path(card.video_id)
    path.write_text(
        json.dumps(card.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def load_index() -> dict[str, Any]:
    if not INDEX_PATH.exists():
        return {"videos": {}, "updated_at": None, "count": 0}
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def rebuild_index() -> dict[str, Any]:
    videos: dict[str, Any] = {}
    for path in sorted(components_dir().glob("*.json")):
        if path.name == "video_components_index.json":
            continue
        try:
            card = VideoComponents.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except Exception:  # noqa: BLE001
            continue
        videos[card.video_id] = {
            "hook_type": card.hook.type,
            "funnel_stage": card.funnel_stage,
            "cta_present": card.cta.present,
            "format_raw": card.format_raw,
            "needs_review": card.extraction.needs_review,
            "inputs_hash": card.extraction.inputs_hash,
            "extracted_at": card.extraction.extracted_at,
        }
    from datetime import datetime, timezone

    index = {
        "videos": videos,
        "count": len(videos),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    return index


def load_all_components() -> list[VideoComponents]:
    out: list[VideoComponents] = []
    for path in sorted(components_dir().glob("*.json")):
        try:
            out.append(
                VideoComponents.model_validate(json.loads(path.read_text(encoding="utf-8")))
            )
        except Exception:  # noqa: BLE001
            continue
    return out
