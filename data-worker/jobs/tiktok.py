"""Thin wrapper — delegates to marketing-pipeline in-process."""

from __future__ import annotations

from marketing_pipeline.tiktok.orchestrator import run_export, run_sync_supabase


def run_tiktok_ingestion(transcripts_path: str | None = None) -> dict:
    """Run export (if needed) then sync-supabase via marketing-pipeline package."""
    _ = transcripts_path  # legacy arg; dataset path is canonical

    export_result = run_export()
    sync_result = run_sync_supabase()
    return {"status": "ok", "export": export_result, "sync": sync_result}
