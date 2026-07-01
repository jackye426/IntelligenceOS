"""Thin wrapper — delegates to marketing-pipeline sync."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MARKETING_PIPELINE = REPO_ROOT / "marketing-pipeline"


def run_tiktok_ingestion(transcripts_path: str | None = None) -> dict[str, int]:
    """Run export (if needed) then sync-supabase via marketing-pipeline package."""
    _ = transcripts_path  # legacy arg; dataset path is canonical

    export_cmd = [sys.executable, "-m", "marketing_pipeline", "tiktok", "export"]
    subprocess.check_call(export_cmd, cwd=str(MARKETING_PIPELINE.parent))

    sync_cmd = [sys.executable, "-m", "marketing_pipeline", "tiktok", "sync-supabase"]
    subprocess.check_call(sync_cmd, cwd=str(MARKETING_PIPELINE.parent))

    return {"status": "ok", "via": "marketing_pipeline"}
