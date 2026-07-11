"""Audit logging for Relationship Desk MCP tools."""

from __future__ import annotations

from typing import Any

from .supabase_client import get_client


def log_tool_call(
    *,
    tool_name: str,
    request_summary: str,
    success: bool,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action_type: str = "read",
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
    caller: str = "relationship_desk",
) -> None:
    try:
        get_client().table("mcp_tool_audit_log").insert(
            {
                "tool_name": tool_name,
                "caller": caller,
                "request_summary": request_summary[:500],
                "entity_type": entity_type,
                "entity_id": entity_id,
                "action_type": action_type,
                "success": success,
                "error": error,
                "metadata": metadata or {},
            }
        ).execute()
    except Exception:
        pass

