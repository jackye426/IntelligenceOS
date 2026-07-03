"""Paths and environment for marketing-pipeline."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PACKAGE_ROOT / "tiktok" / "data"

load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(REPO_ROOT / ".env")

LEGACY_TIKTOK_ROOT = REPO_ROOT / "Social media analysis" / "tiktok_analysis"
LEGACY_SCRIPTS = LEGACY_TIKTOK_ROOT / "scripts"

TRANSCRIPTS_DIR = DATA_ROOT / "transcripts"
CATALOG_DIR = DATA_ROOT / "catalog"
COMMENTS_RAW_DIR = DATA_ROOT / "comments_raw"
ANALYSIS_DIR = DATA_ROOT / "analysis"
EXPORTS_DIR = DATA_ROOT / "exports"
MEDIA_DIR = DATA_ROOT / "media"
OCR_CACHE_DIR = DATA_ROOT / "ocr"
YT_META_DIR = DATA_ROOT / "yt_meta"
PLAYBOOKS_DIR = DATA_ROOT / "playbooks"
LEGACY_MEDIA_DIR = LEGACY_TIKTOK_ROOT / "audio"

MASTER_TRANSCRIPTS = TRANSCRIPTS_DIR / "ALL_COMPLETE_TRANSCRIPTS.txt"
DATASET_JSON = EXPORTS_DIR / "tiktok_marketing_dataset.json"
ALL_COMMENTS_TXT = EXPORTS_DIR / "ALL_COMMENTS.txt"
DATASET_VERSION = "2"
COMMENT_STALE_DAYS = 7


def _getenv(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


SUPABASE_URL = _getenv("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = _getenv("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY")
OPENROUTER_API_KEY = _getenv("OPENROUTER_API_KEY")
OPENROUTER_EMBEDDING_MODEL = _getenv(
    "OPENROUTER_EMBEDDING_MODEL", default="openai/text-embedding-3-small"
)
MODEL_OCR = _getenv("MODEL_OCR", default="google/gemini-3-flash-preview")
FFMPEG_PATH = _getenv("FFMPEG_PATH", default="ffmpeg")
WHISPER_MODEL = _getenv("WHISPER_MODEL", default="small")
