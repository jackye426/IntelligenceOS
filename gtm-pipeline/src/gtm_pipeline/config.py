"""Paths and environment for gtm-pipeline."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# src/gtm_pipeline/config.py -> gtm_pipeline -> src -> gtm-pipeline -> repo
REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(REPO_ROOT / ".env")


def _getenv(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def _resolve_dir(env_name: str, default_rel: str) -> Path:
    explicit = _getenv(env_name)
    path = Path(explicit) if explicit else REPO_ROOT / default_rel
    path.mkdir(parents=True, exist_ok=True)
    return path


DATA_DIR = _resolve_dir("GTM_DATA_DIR", "data/gtm")

# Prefer gtm-owned path (Railway: under GTM_DATA_DIR). Legacy Clinic sales
# output path is only used if that file exists and no override is set.
def _default_cqc_directory() -> Path:
    explicit = _getenv("CQC_DIRECTORY_PATH")
    if explicit:
        return Path(explicit)
    gtm_copy = DATA_DIR / "cqc_directory.csv"
    package_data = PACKAGE_ROOT / "data" / "cqc_directory.csv"
    legacy = REPO_ROOT / "Clinic sales agent" / "output" / "cqc_directory.csv"
    if gtm_copy.exists():
        return gtm_copy
    if package_data.exists():
        return package_data
    if legacy.exists():
        return legacy
    # Default write target for auto-refresh (Railway / fresh clones)
    return gtm_copy


CQC_DIRECTORY_PATH = _default_cqc_directory()
CQC_DIRECTORY_MAX_AGE_DAYS = int(_getenv("CQC_DIRECTORY_MAX_AGE_DAYS", default="7") or "7")


def _default_doctify_scope() -> Path:
    explicit = _getenv("DOCTIFY_SCOPE_CSV")
    if explicit:
        return Path(explicit)
    candidates = [
        Path("/app/config/doctify_scope.csv"),  # Railway / Docker WORKDIR
        PACKAGE_ROOT / "config" / "doctify_scope.csv",  # editable: gtm-pipeline/config
        REPO_ROOT / "gtm-pipeline" / "config" / "doctify_scope.csv",
        Path.cwd() / "config" / "doctify_scope.csv",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


DOCTIFY_SCOPE_CSV = _default_doctify_scope()


SUPABASE_URL = _getenv("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = _getenv("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY")
CQC_API_KEY = _getenv("CQC_API_KEY")
ROCKETREACH_API_KEY = _getenv("ROCKETREACH_API_KEY", "GTM_ROCKETREACH_API_KEY")

MATCH_AUTO_ACCEPT = float(_getenv("GTM_MATCH_AUTO_ACCEPT", default="0.80"))
MATCH_REVIEW_THRESHOLD = float(_getenv("GTM_MATCH_REVIEW_THRESHOLD", default="0.50"))

# Doctify practice page fixture used for live smoke / docs
DOCTIFY_FIXTURE_URL = (
    "https://www.doctify.com/uk/practice/london-gynaecology-harley-street#specialists"
)
