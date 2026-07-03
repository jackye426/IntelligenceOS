"""Bootstrap marketing-pipeline data directory on fresh deploys (e.g. Railway)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from marketing_pipeline import config

logger = logging.getLogger(__name__)

_DEFAULT_REPO = "https://github.com/jackye426/IntelligenceOS.git"


def _ensure_subdirs() -> None:
    for path in (
        config.TRANSCRIPTS_DIR,
        config.CATALOG_DIR,
        config.COMMENTS_RAW_DIR,
        config.ANALYSIS_DIR,
        config.EXPORTS_DIR,
        config.PLAYBOOKS_DIR,
        config.MEDIA_DIR,
        config.OCR_CACHE_DIR,
        config.YT_META_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def seed_from_github(*, branch: str | None = None) -> bool:
    """Clone tiktok/data from GitHub into MARKETING_DATA_DIR when empty."""
    if config.MASTER_TRANSCRIPTS.exists():
        return False

    repo = os.getenv("MARKETING_DATA_REPO", _DEFAULT_REPO)
    branch = branch or os.getenv("MARKETING_DATA_BRANCH", "main")

    with tempfile.TemporaryDirectory() as tmp:
        clone_dir = Path(tmp) / "repo"
        logger.info("Seeding pipeline data from %s@%s", repo, branch)
        subprocess.check_call(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                branch,
                repo,
                str(clone_dir),
            ]
        )
        src = clone_dir / "marketing-pipeline" / "tiktok" / "data"
        if not src.is_dir():
            raise FileNotFoundError(f"Expected pipeline data at {src}")

        _ensure_subdirs()
        for item in src.iterdir():
            dest = config.DATA_ROOT / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
    logger.info("Pipeline data seeded at %s", config.DATA_ROOT)
    return True


def ensure_pipeline_data() -> dict:
    """Create data dirs; seed from GitHub on first run if transcripts are missing."""
    _ensure_subdirs()
    seeded = seed_from_github()
    return {
        "data_root": str(config.DATA_ROOT),
        "master_exists": config.MASTER_TRANSCRIPTS.exists(),
        "seeded": seeded,
    }
