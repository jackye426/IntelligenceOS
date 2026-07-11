"""Chase status update tools."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from common.audit import log_tool_call
from common.relationship_store import add_event, get_chase, list_events, update_chase


def mark_waiting(*, chase_id: str, next_chase_due_at: str | None = None, note: str | None = None) -> dict[str, Any]:
    try:
        due_at = next_chase_due_at or (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        chase = update_chase(chase_id, {"status": "waiting", "next_chase_due_at": due_at, "notes": note})
        add_event(chase_id=chase_id, event_type="marked_waiting", summary=note or "Marked waiting")
        log_tool_call(tool_name="mark_waiting", request_summary=chase_id, success=True, entity_id=chase_id, action_type="write")
        return {"chase": chase}
    except Exception as exc:
        log_tool_call(tool_name="mark_waiting", request_summary=chase_id, success=False, error=str(exc))
        raise


def mark_done(*, chase_id: str, outcome: str | None = None) -> dict[str, Any]:
    try:
        chase = update_chase(chase_id, {"status": "done", "notes": outcome})
        add_event(chase_id=chase_id, event_type="marked_done", summary=outcome or "Marked done")
        log_tool_call(tool_name="mark_done", request_summary=chase_id, success=True, entity_id=chase_id, action_type="write")
        return {"chase": chase}
    except Exception as exc:
        log_tool_call(tool_name="mark_done", request_summary=chase_id, success=False, error=str(exc))
        raise


def snooze(*, chase_id: str, until: str, note: str | None = None) -> dict[str, Any]:
    try:
        chase = update_chase(chase_id, {"next_chase_due_at": until, "status": "waiting", "notes": note})
        add_event(chase_id=chase_id, event_type="snoozed", summary=note or f"Snoozed until {until}")
        log_tool_call(tool_name="snooze_chase", request_summary=chase_id, success=True, entity_id=chase_id, action_type="write")
        return {"chase": chase}
    except Exception as exc:
        log_tool_call(tool_name="snooze_chase", request_summary=chase_id, success=False, error=str(exc))
        raise


def relationship_brief(*, chase_id: str) -> dict[str, Any]:
    try:
        chase = get_chase(chase_id)
        events = list_events(chase_id)
        log_tool_call(tool_name="get_relationship_brief", request_summary=chase_id, success=True, entity_id=chase_id)
        return {"chase": chase, "events": events}
    except Exception as exc:
        log_tool_call(tool_name="get_relationship_brief", request_summary=chase_id, success=False, error=str(exc))
        raise
