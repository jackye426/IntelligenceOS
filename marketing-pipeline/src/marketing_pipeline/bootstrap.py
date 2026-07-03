"""Bootstrap marketing-pipeline data directory on fresh deploys (e.g. Railway)."""

from __future__ import annotations

import io
import logging
import os
import tarfile
from pathlib import Path

import httpx

from marketing_pipeline import config

logger = logging.getLogger(__name__)

_DEFAULT_SLUG = "jackye426/IntelligenceOS"


def _github_slug() -> str:
    repo = os.getenv("MARKETING_DATA_REPO", _DEFAULT_SLUG)
    if "github.com/" in repo:
        return repo.split("github.com/", 1)[1].replace(".git", "").strip("/")
    return repo.replace(".git", "").strip("/")


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
    """Download tiktok/data from GitHub tarball into MARKETING_DATA_DIR (no git binary)."""
    if config.MASTER_TRANSCRIPTS.exists():
        return False

    branch = branch or os.getenv("MARKETING_DATA_BRANCH", "main")
    slug = _github_slug()
    url = f"https://codeload.github.com/{slug}/tar.gz/{branch}"
    repo_name = slug.split("/")[-1]
    prefix = f"{repo_name}-{branch}/marketing-pipeline/tiktok/data/"

    logger.info("Seeding pipeline data from %s", url)
    _ensure_subdirs()

    with httpx.Client(timeout=httpx.Timeout(180.0, connect=30.0)) as client:
        response = client.get(url)
        response.raise_for_status()
        archive = response.content

    extracted = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.isdir() or not member.name.startswith(prefix):
                continue
            rel = member.name[len(prefix) :]
            if not rel:
                continue
            dest = config.DATA_ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(member)
            if src is None:
                continue
            dest.write_bytes(src.read())
            extracted += 1

    if extracted == 0:
        raise FileNotFoundError(f"No pipeline data found under archive path {prefix}")

    logger.info("Pipeline data seeded at %s (%s files)", config.DATA_ROOT, extracted)
    return True


def ensure_pipeline_data() -> dict:
    """Create data dirs; seed from GitHub on first run if transcripts are missing."""
    _ensure_subdirs()
    seeded = False
    error: str | None = None
    try:
        seeded = seed_from_github()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Pipeline data seed failed")
        error = str(exc)
    return {
        "data_root": str(config.DATA_ROOT),
        "master_exists": config.MASTER_TRANSCRIPTS.exists(),
        "seeded": seeded,
        "error": error,
    }
