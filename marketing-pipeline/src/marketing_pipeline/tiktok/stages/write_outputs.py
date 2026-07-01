"""Write dataset JSON and ensure master transcripts path exists."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from marketing_pipeline.tiktok.models import TikTokMarketingDataset


def write_dataset(dataset: TikTokMarketingDataset, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dataset.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def ensure_master_transcripts(source: Path, dest: Path) -> Path:
    """Copy or symlink master txt to exports if needed."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != dest.resolve():
        shutil.copy2(source, dest)
    return dest
