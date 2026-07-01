"""Import strategy playbooks into package data root."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from marketing_pipeline import config

DEFAULT_SOURCES = {
    "content-instruction.md": Path.home() / "Downloads" / "DocMap-TikTok-Content-Instruction.txt",
    "viral-format.md": Path.home() / "Downloads" / "Viral-video-format.txt",
}


def import_playbooks(extra_sources: dict[str, Path] | None = None) -> dict[str, str]:
    config.PLAYBOOKS_DIR.mkdir(parents=True, exist_ok=True)
    (config.PLAYBOOKS_DIR / "evidence").mkdir(parents=True, exist_ok=True)
    (config.PLAYBOOKS_DIR / "evidence" / "_drafts").mkdir(parents=True, exist_ok=True)

    sources = {**DEFAULT_SOURCES, **(extra_sources or {})}
    copied: dict[str, str] = {}

    for dest_name, src in sources.items():
        if not src.exists():
            continue
        dest = config.PLAYBOOKS_DIR / dest_name
        shutil.copy2(src, dest)
        copied[dest_name] = str(dest)

    recipe_src = config.ANALYSIS_DIR / "RECIPE_AND_HYPOTHESES.md"
    if recipe_src.exists():
        dest = config.PLAYBOOKS_DIR / "evidence" / "recipe-2026-06.md"
        header = (
            "---\n"
            "status: approved\n"
            "as_of: 2026-06-01\n"
            "video_count: 8\n"
            "note: Historical 8-video cohort synthesis; verify metrics against live dataset\n"
            "---\n\n"
        )
        dest.write_text(header + recipe_src.read_text(encoding="utf-8"), encoding="utf-8")
        copied["recipe-2026-06.md"] = str(dest)

    index = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "playbooks": [
            {"slug": name, "path": path, "status": "approved"}
            for name, path in copied.items()
        ],
    }
    (config.PLAYBOOKS_DIR / "playbook_index.json").write_text(
        json.dumps(index, indent=2),
        encoding="utf-8",
    )
    return copied
