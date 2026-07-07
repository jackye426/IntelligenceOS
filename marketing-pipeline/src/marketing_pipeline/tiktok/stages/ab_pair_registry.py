"""Load explicit A/B pair registry (human-curated hook tests)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from marketing_pipeline import config

REGISTRY_PATH = config.ANALYSIS_DIR / "ab_pair_registry.json"


def validate_registry_pairs(entries: list[dict[str, Any]]) -> list[str]:
    """Return human-readable errors. Variant groups: 2–4 videos, no reuse across groups."""
    errors: list[str] = []
    seen_videos: dict[str, str] = {}

    for entry in entries:
        group_id = str(entry.get("pair_id") or entry.get("group_id") or "<unknown>")
        ids = [str(v) for v in entry.get("video_ids") or [] if v]
        if len(ids) < 2 or len(ids) > 4:
            errors.append(
                f"{group_id}: expected 2–4 video_ids, got {len(ids)}"
            )
            continue
        if len(set(ids)) != len(ids):
            errors.append(f"{group_id}: duplicate video_id in group")
            continue
        for vid in ids:
            if vid in seen_videos:
                errors.append(
                    f"{group_id}: video {vid} already in group {seen_videos[vid]}"
                )
            else:
                seen_videos[vid] = group_id

    return errors


def load_registry_pairs(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or REGISTRY_PATH
    if not target.exists():
        return []
    data = json.loads(target.read_text(encoding="utf-8"))
    entries = list(data.get("pairs") or [])
    errors = validate_registry_pairs(entries)
    if errors:
        raise ValueError("Invalid ab_pair_registry.json:\n" + "\n".join(errors))
    return entries
