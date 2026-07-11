"""Draft follow-up copy for a chase."""

from __future__ import annotations

from typing import Any

from common import config
from common.audit import log_tool_call
from common.drafting import draft_followup
from common.gmail_client import get_thread
from common.relationship_store import get_chase
from common.safety import classify_message


def run(*, chase_id: str, tone: str = "warm") -> dict[str, Any]:
    try:
        chase = get_chase(chase_id)
        thread = None
        if chase.get("gmail_thread_id"):
            thread = get_thread(chase["gmail_thread_id"], max_messages=config.MAX_THREAD_MESSAGES)
        draft = draft_followup(chase, thread=thread, tone=tone)
        contact = chase.get("relationship_contacts") or {}
        safety = classify_message(
            body=draft["body"],
            to_email=contact.get("email"),
            objective=chase.get("objective"),
        )
        log_tool_call(
            tool_name="draft_chase",
            request_summary=chase_id,
            success=True,
            entity_type="relationship_chase",
            entity_id=chase_id,
        )
        return {"chase": chase, "draft": draft, "safety": safety}
    except Exception as exc:
        log_tool_call(tool_name="draft_chase", request_summary=chase_id, success=False, error=str(exc))
        raise
