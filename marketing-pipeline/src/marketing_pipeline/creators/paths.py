"""Per-call paths for the creator corpus. Never DocMap's TikTok tree."""

from __future__ import annotations

import os
from pathlib import Path

from marketing_pipeline import config

_PKG_DIR = Path(__file__).resolve().parent


def _dev_package_root() -> Path:
    return _PKG_DIR.parent.parent.parent


def creators_data_dir() -> Path:
    """Resolve the corpus cache root for this call (not process-global)."""
    explicit = os.getenv("MARKETING_CREATORS_DATA_DIR")
    if explicit:
        root = Path(explicit)
    else:
        root = _dev_package_root() / "creators" / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def research_profile_dir() -> Path:
    path = creators_data_dir() / ".tiktok_research_profile"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def profile_cache_dir() -> Path:
    path = creators_data_dir() / "profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def assert_isolated_from_docmap() -> None:
    """Hard-fail if the corpus cache sits on DocMap's data root or Studio profile."""
    from marketing_pipeline.tiktok.stages.studio_listen import profile_dir as studio_profile_dir

    creators = creators_data_dir()
    docmap = Path(config.DOCMAP_DATA_ROOT).resolve()
    studio = studio_profile_dir().resolve()
    research = research_profile_dir()

    if creators == docmap or docmap in creators.parents or creators in docmap.parents:
        raise RuntimeError(
            f"CREATORS_DATA_DIR {creators} collides with DocMap data root {docmap}"
        )
    if research == studio or studio in research.parents or research in studio.parents:
        raise RuntimeError(
            f"research TikTok profile {research} collides with Studio profile {studio}"
        )


def pending_tiktok_user_id(handle: str) -> str:
    return f"pending:{normalise_handle(handle)}"


def normalise_handle(handle: str) -> str:
    return (handle or "").strip().lstrip("@").lower()
