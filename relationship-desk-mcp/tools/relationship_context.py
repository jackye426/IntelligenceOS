"""Relationship context MCP tools."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from common.relationship_context import build_context


def get(
    *,
    contact_hint: str | None = None,
    email: str | None = None,
    chase_id: str | None = None,
    days_back: int = 180,
    include_live_gmail: bool = True,
) -> dict[str, Any]:
    try:
        result = build_context(
            contact_hint=contact_hint,
            email=email,
            chase_id=chase_id,
            days_back=days_back,
            include_live_gmail=include_live_gmail,
        )
        log_tool_call(
            tool_name="get_relationship_context",
            request_summary=chase_id or email or contact_hint,
            success=True,
            entity_type="relationship_contact" if result.get("contact") else None,
            entity_id=(result.get("contact") or {}).get("id"),
        )
        return result
    except Exception as exc:
        log_tool_call(
            tool_name="get_relationship_context",
            request_summary=chase_id or email or contact_hint,
            success=False,
            error=str(exc),
        )
        raise
