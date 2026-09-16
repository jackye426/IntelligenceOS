"""Crawl-run counters. Degraded runs exit non-zero at the CLI layer."""

from __future__ import annotations

from typing import Any

from marketing_pipeline.creators.store import get_store

EXIT_OK = 0
EXIT_DEGRADED = 2
EXIT_BLOCKED = 3
EXIT_FAILED = 1


def start_run(
    command: str,
    *,
    source: str | None = None,
    params: dict[str, Any] | None = None,
    worker: str | None = None,
    store=None,
) -> dict[str, Any]:
    store = store or get_store()
    return store.insert(
        "creator_crawl_runs",
        {
            "command": command,
            "source": source,
            "params": params or {},
            "status": "running",
            "counters": {},
            "budget": {},
            "expectations": {},
            "worker": worker,
        },
    )


def finish_run(
    run_id: str,
    *,
    status: str,
    counters: dict[str, Any] | None = None,
    error: str | None = None,
    store=None,
) -> None:
    store = store or get_store()
    from datetime import datetime, timezone

    store.update(
        "creator_crawl_runs",
        {
            "status": status,
            "counters": counters or {},
            "error": error,
            "finished_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        },
        id=run_id,
    )


def exit_code(status: str) -> int:
    return {
        "completed": EXIT_OK,
        "degraded": EXIT_DEGRADED,
        "blocked": EXIT_BLOCKED,
        "failed": EXIT_FAILED,
    }.get(status, EXIT_FAILED)
