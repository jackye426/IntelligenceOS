"""Paths and environment for ingestion-pipeline."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# src/ingestion_pipeline/config.py -> ingestion_pipeline -> src -> ingestion-pipeline -> repo
REPO_ROOT = Path(__file__).resolve().parents[3]

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


IMPORTS_DIR = _resolve_dir("INGESTION_IMPORTS_DIR", "data/imports")
STAGING_DIR = _resolve_dir("INGESTION_STAGING_DIR", "data/staging")
REVIEW_QUEUE = STAGING_DIR / "review_queue.jsonl"

CLASSIFY_THRESHOLD = float(_getenv("INGESTION_CLASSIFY_THRESHOLD", default="0.85"))

CLINIC_SALES_CSV_PATH = Path(
    _getenv(
        "CLINIC_SALES_CSV_PATH",
        default=str(REPO_ROOT / "Clinic sales agent" / "output" / "clinic_sales_results.csv"),
    )
)

SUPABASE_URL = _getenv("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = _getenv("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY")
OPENROUTER_API_KEY = _getenv("OPENROUTER_API_KEY")
OPENROUTER_EMBEDDING_MODEL = _getenv(
    "OPENROUTER_EMBEDDING_MODEL", default="openai/text-embedding-3-small"
)
