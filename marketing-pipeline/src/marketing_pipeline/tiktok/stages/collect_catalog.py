"""Load catalog JSON files for the active account."""

from __future__ import annotations

import json
from pathlib import Path

from marketing_pipeline import config


def load_catalog(catalog_dir: Path, *, handle: str | None = None) -> dict[str, dict]:
    videos: dict[str, dict] = {}
    for path in sorted(catalog_dir.glob(config.catalog_glob(handle))):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            vid = str(entry.get("video_id", ""))
            if vid and vid not in videos:
                videos[vid] = entry
    return videos
