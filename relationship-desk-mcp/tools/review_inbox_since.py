"""Review recent inbox messages that may need relationship attention."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from common.gmail_client import search_threads


def run(*, since: str, max_results: int = 20) -> dict[str, Any]:
    query = f"in:inbox after:{since}"
    try:
        threads = search_threads(query, max_results=max_results)
        log_tool_call(tool_name="review_inbox_since", request_summary=query, success=True)
        return {
            "query": query,
            "count": len(threads),
            "threads": threads,
            "note": "Use capture_chase for any thread that needs a tracked follow-up.",
        }
    except Exception as exc:
        log_tool_call(tool_name="review_inbox_since", request_summary=query, success=False, error=str(exc))
        raise
