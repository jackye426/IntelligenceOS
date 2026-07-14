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
CQC_DIRECTORY_PATH = Path(
    _getenv(
        "CQC_DIRECTORY_PATH",
        default=str(REPO_ROOT / "Clinic sales agent" / "output" / "cqc_directory.csv"),
    )
)

SUPABASE_URL = _getenv("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = _getenv("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY")
CQC_API_KEY = _getenv("CQC_API_KEY")

MATCH_AUTO_ACCEPT = float(_getenv("GTM_MATCH_AUTO_ACCEPT", default="0.80"))
MATCH_REVIEW_THRESHOLD = float(_getenv("GTM_MATCH_REVIEW_THRESHOLD", default="0.50"))

# Doctify practice page fixture used for live smoke / docs
DOCTIFY_FIXTURE_URL = (
    "https://www.doctify.com/uk/practice/london-gynaecology-harley-street#specialists"
)
