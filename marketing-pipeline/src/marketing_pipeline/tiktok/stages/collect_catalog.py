"""Load docmap catalog JSON files."""

from __future__ import annotations

import json
from pathlib import Path


def load_catalog(catalog_dir: Path) -> dict[str, dict]:
    videos: dict[str, dict] = {}
    for path in sorted(catalog_dir.glob("docmap_catalog_since_*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            vid = str(entry.get("video_id", ""))
            if vid and vid not in videos:
                videos[vid] = entry
    return videos
