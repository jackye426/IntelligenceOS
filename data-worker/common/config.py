"""Environment configuration for the data worker."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(REPO_ROOT / ".env")


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
PRACTITIONERS_TABLE = _getenv(
    "SUPABASE_PRACTITIONERS_TABLE", default="integrated_practitioner_with_phin"
)

SKIP_CONTENT_TRACKER = _getenv("SKIP_CONTENT_TRACKER", default="false").lower() in {
    "1",
    "true",
    "yes",
}
SKIP_HCA = _getenv("SKIP_HCA", default="false").lower() in {"1", "true", "yes"}

# TikTok pipeline: transcribe new catalog videos on worker (set true to disable)
SKIP_TRANSCRIBE = _getenv("SKIP_TRANSCRIBE", default="false").lower() in {
    "1",
    "true",
    "yes",
}

# Studio Playwright insight capture (slow, 2x/week). Set true to disable.
SKIP_STUDIO_LISTEN = _getenv("SKIP_STUDIO_LISTEN", default="false").lower() in {
    "1",
    "true",
    "yes",
}

# Writable pipeline data root on Railway (mount a volume at this path)
MARKETING_DATA_DIR = _getenv("MARKETING_DATA_DIR", default="/app/marketing-data")
WHISPER_MODEL = _getenv("WHISPER_MODEL", default="small")

CONTENT_TRACKER_CSV = REPO_ROOT / (
    "Social media analysis/Marketing - Content - Tracker - Content Tracker (3).csv"
)
TIKTOK_ANALYSIS_DIR = REPO_ROOT / "marketing-pipeline/tiktok/data"
TIKTOK_ALL_TRANSCRIPTS = (
    TIKTOK_ANALYSIS_DIR / "transcripts/ALL_COMPLETE_TRANSCRIPTS.txt"
)
MARKETING_PIPELINE_ROOT = REPO_ROOT / "marketing-pipeline"
HCA_SQLITE_PATH = REPO_ROOT / (
    "Appointment utilization rate/hca-monitor/data/hca_monitor.db"
)
