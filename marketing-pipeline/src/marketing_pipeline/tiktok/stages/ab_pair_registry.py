"""Load explicit A/B pair registry (human-curated hook tests)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from marketing_pipeline import config

REGISTRY_PATH = config.ANALYSIS_DIR / "ab_pair_registry.json"


def load_registry_pairs(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or REGISTRY_PATH
    if not target.exists():
        return []
    data = json.loads(target.read_text(encoding="utf-8"))
    return list(data.get("pairs") or [])
