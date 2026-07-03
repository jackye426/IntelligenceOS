"""Legacy refresh adapter — delegates to package-native stages."""

from __future__ import annotations

import shutil
from pathlib import Path

from marketing_pipeline import config
from marketing_pipeline.tiktok.stages.fetch_catalog import fetch_catalog
from marketing_pipeline.tiktok.stages.refresh_videos import refresh_videos
from marketing_pipeline.tiktok.stages.write_master_transcripts import write_master_transcripts


def copy_legacy_artifacts() -> dict[str, int]:
    """One-way sync from legacy data/ into package data/ (migration helper)."""
    legacy = config.LEGACY_TIKTOK_ROOT / "data"
    counts: dict[str, int] = {}

    mappings = [
        (legacy / "transcripts", config.TRANSCRIPTS_DIR),
        (legacy / "comments_raw", config.COMMENTS_RAW_DIR),
        (legacy / "analysis", config.ANALYSIS_DIR),
        (legacy / "yt_meta", config.YT_META_DIR),
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
            elif not target.exists():
                shutil.copy2(item, target)
            n += 1
        counts[str(dst_dir.name)] = n

    for path in legacy.glob("docmap_catalog_*.json"):
        config.CATALOG_DIR.mkdir(parents=True, exist_ok=True)
        target = config.CATALOG_DIR / path.name
        if not target.exists():
            shutil.copy2(path, target)
        counts["catalog"] = counts.get("catalog", 0) + 1

    return counts


def run_legacy_refresh(
    *,
    since: str = "2026-04-20",
    skip_transcribe: bool = False,
    skip_catalog: bool = False,
    skip_compile: bool = False,
    whisper_model: str | None = None,
) -> dict:
    """Deprecated shim — runs package-native refresh (no subprocess)."""
    if not skip_catalog:
        fetch_catalog(since=since)
    video_result = refresh_videos(
        since=since,
        skip_transcribe=skip_transcribe,
        whisper_model=whisper_model,
        download_if_missing=True,
    )
    master_result: dict = {}
    if not skip_compile:
        master_result = write_master_transcripts(refresh_metrics=True)
    return {"videos": video_result, "master": master_result}
