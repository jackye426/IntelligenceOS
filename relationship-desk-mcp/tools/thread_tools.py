"""Gmail thread search and briefing tools."""

from __future__ import annotations

from typing import Any

from common import config
from common.audit import log_tool_call
from common.drafting import brief_thread
from common.gmail_client import get_thread, search_threads


def search(*, query: str, max_results: int = 10) -> dict[str, Any]:
    try:
        threads = search_threads(query, max_results=max_results)
        log_tool_call(tool_name="search_threads", request_summary=query, success=True)
        return {"query": query, "count": len(threads), "threads": threads}
    except Exception as exc:
        log_tool_call(tool_name="search_threads", request_summary=query, success=False, error=str(exc))
        raise


def brief(*, gmail_thread_id: str) -> dict[str, Any]:
    try:
        thread = get_thread(gmail_thread_id, max_messages=config.MAX_THREAD_MESSAGES)
        result = {"brief": brief_thread(thread), "thread": thread}
        log_tool_call(
            tool_name="get_thread_brief",
            request_summary=gmail_thread_id,
            success=True,
            entity_type="gmail_thread",
            entity_id=gmail_thread_id,
        )
        return result
    except Exception as exc:
        log_tool_call(tool_name="get_thread_brief", request_summary=gmail_thread_id, success=False, error=str(exc))
        raise
