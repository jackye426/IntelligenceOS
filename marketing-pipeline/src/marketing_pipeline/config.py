"""Paths and environment for marketing-pipeline."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_PKG_DIR = Path(__file__).resolve().parent


def _getenv(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def _dev_package_root() -> Path:
    """marketing-pipeline/ when running from src layout."""
    return _PKG_DIR.parent.parent


def _resolve_data_root() -> Path:
    explicit = _getenv("MARKETING_DATA_DIR")
    if explicit:
        root = Path(explicit)
        root.mkdir(parents=True, exist_ok=True)
        return root

    dev_data = _dev_package_root() / "tiktok" / "data"
    if dev_data.is_dir():
        return dev_data

    # Railway / pip install: writable default (mount a volume here in prod)
    cache = Path("/app/marketing-data")
    cache.mkdir(parents=True, exist_ok=True)
    return cache


REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = _dev_package_root()
DATA_ROOT = _resolve_data_root()

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


SUPABASE_URL = _getenv("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = _getenv("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY")
OPENROUTER_API_KEY = _getenv("OPENROUTER_API_KEY")
OPENROUTER_EMBEDDING_MODEL = _getenv(
    "OPENROUTER_EMBEDDING_MODEL", default="openai/text-embedding-3-small"
)
MODEL_OCR = _getenv("MODEL_OCR", default="google/gemini-3-flash-preview")
FFMPEG_PATH = _getenv("FFMPEG_PATH", default="ffmpeg")
WHISPER_MODEL = _getenv("WHISPER_MODEL", default="small")


def _getint(name: str, default: int) -> int:
    raw = _getenv(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


# Cap CTranslate2 CPU threads. On high-core hosts (e.g. 8 vCPU) the default of
# "all cores" inflates memory per model. 4 is a safe balance for Whisper small.
WHISPER_CPU_THREADS = _getint("WHISPER_CPU_THREADS", 4)
