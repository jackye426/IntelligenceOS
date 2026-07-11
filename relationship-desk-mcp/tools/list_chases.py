"""List relationship chase items."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from common.audit import log_tool_call
from common.relationship_store import list_chases, now_iso


def run(
    *,
    status: str | None = None,
    due_before: str | None = None,
    limit: int = 30,
    include_done: bool = False,
) -> dict[str, Any]:
    try:
        rows = list_chases(
            status=status,
            due_before=due_before,
            limit=limit,
            include_done=include_done,
        )
        log_tool_call(tool_name="list_chases", request_summary=status or "open", success=True)
        return {"as_of": now_iso(), "count": len(rows), "chases": rows}
    except Exception as exc:
        log_tool_call(tool_name="list_chases", request_summary=status or "open", success=False, error=str(exc))
        raise


def due_now(*, limit: int = 20) -> dict[str, Any]:
    return run(due_before=datetime.now(timezone.utc).isoformat(), limit=limit)
