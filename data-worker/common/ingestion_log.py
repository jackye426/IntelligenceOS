"""data_ingestion_runs helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .supabase_client import get_client


def start_run(job_name: str, metadata: dict[str, Any] | None = None) -> str:
    client = get_client()
    row = {
        "job_name": job_name,
        "status": "started",
        "metadata": metadata or {},
    }
    result = client.table("data_ingestion_runs").insert(row).execute()
    return result.data[0]["id"]


def finish_run(
    run_id: str,
    status: str,
    counts: dict[str, int],
    error: str | None = None,
) -> None:
    client = get_client()
    client.table("data_ingestion_runs").update(
        {
            "status": status,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "rows_seen": counts.get("rows_seen", 0),
            "rows_inserted": counts.get("rows_inserted", 0),
            "rows_updated": counts.get("rows_updated", 0),
            "error": error,
        }
    ).eq("id", run_id).execute()
