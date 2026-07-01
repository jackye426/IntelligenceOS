"""Run legacy refresh_docmap.py and copy artifacts into package data root."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from marketing_pipeline import config


def copy_legacy_artifacts() -> dict[str, int]:
    legacy = config.LEGACY_TIKTOK_ROOT / "data"
    counts: dict[str, int] = {}

    mappings = [
        (legacy / "transcripts", config.TRANSCRIPTS_DIR),
        (legacy / "comments_raw", config.COMMENTS_RAW_DIR),
        (legacy / "analysis", config.ANALYSIS_DIR),
    ]
    for src_dir, dst_dir in mappings:
        if not src_dir.exists():
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)
        n = 0
        for item in src_dir.iterdir():
            target = dst_dir / item.name
            if item.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)
            n += 1
        counts[str(dst_dir.name)] = n

    catalog_src = legacy.parent / "analysis"
    if catalog_src.exists():
        config.ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
        for path in catalog_src.glob("comments_labeled_*.json"):
            shutil.copy2(path, config.ANALYSIS_DIR / path.name)

    for path in legacy.glob("docmap_catalog_*.json"):
        config.CATALOG_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, config.CATALOG_DIR / path.name)
        counts["catalog"] = counts.get("catalog", 0) + 1

    legacy_analysis = config.LEGACY_TIKTOK_ROOT / "analysis"
    if legacy_analysis.exists():
        config.ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
        for path in legacy_analysis.iterdir():
            shutil.copy2(path, config.ANALYSIS_DIR / path.name)

    return counts


def run_legacy_refresh(*, since: str = "2026-04-20", skip_transcribe: bool = False) -> None:
    script = config.LEGACY_SCRIPTS / "refresh_docmap.py"
    if not script.exists():
        raise FileNotFoundError(f"Legacy refresh script not found: {script}")

    cmd = [sys.executable, str(script), "--since", since]
    if skip_transcribe:
        cmd.append("--skip-transcribe")
    subprocess.check_call(cmd, cwd=str(config.LEGACY_TIKTOK_ROOT))
