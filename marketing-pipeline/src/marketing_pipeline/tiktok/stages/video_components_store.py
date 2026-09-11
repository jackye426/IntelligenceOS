"""Sidecar + index I/O for video component cards."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from marketing_pipeline import config
from marketing_pipeline.tiktok.stages.video_components_models import VideoComponents

# Resolved per call, never at import. `config.ANALYSIS_DIR` is rebound by
# config.activate_account(), but cli.py imports this module (via orchestrator)
# BEFORE the account is activated. As module-level constants these paths froze
# to DocMap's tree, so a peer run wrote its component cards straight into the
# owned library. Keep them functions.


def components_dir() -> Path:
    path = config.ANALYSIS_DIR / "video_components"
    path.mkdir(parents=True, exist_ok=True)
    return path


def index_path() -> Path:
    return config.ANALYSIS_DIR / "video_components_index.json"


def __getattr__(name: str):
    """Back-compat for callers that still read the old module constants."""
    if name == "COMPONENTS_DIR":
        return components_dir()
    if name == "INDEX_PATH":
        return index_path()
    raise AttributeError(name)


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
    if not index_path().exists():
        return {"videos": {}, "updated_at": None, "count": 0}
    return json.loads(index_path().read_text(encoding="utf-8"))


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
    index_path().parent.mkdir(parents=True, exist_ok=True)
    index_path().write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
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
