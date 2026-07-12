"""Create Gmail drafts or send approved safe chase messages."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from common.audit import log_tool_call
from common.drafting import draft_followup
from common.gmail_client import create_draft, get_thread, send_message
from common.relationship_context import build_context
from common.relationship_store import add_event, get_chase, update_chase
from common.safety import classify_message, mode_allows_send


def run(
    *,
    chase_id: str,
    action: str = "draft",
    confirmed: bool = False,
    subject: str | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    try:
        chase = get_chase(chase_id)
        contact = chase.get("relationship_contacts") or {}
        context = build_context(chase_id=chase_id, include_live_gmail=True)
        thread = get_thread(chase["gmail_thread_id"]) if chase.get("gmail_thread_id") else None
        if not subject or not body:
            drafted = draft_followup(chase, thread=thread)
            subject = subject or drafted["subject"]
            body = body or drafted["body"]

        to_email = contact.get("email")
        safety = classify_message(body=body, to_email=to_email, objective=chase.get("objective"))
        should_send = action in {"send", "send_if_safe"} and mode_allows_send(
            confirmed=confirmed,
            safe_to_send=safety["safe_to_send"],
        )

        if should_send:
            result = send_message(
                subject=subject,
                body=body,
                to_email=to_email,
                thread_id=chase.get("gmail_thread_id"),
            )
            update_chase(
                chase_id,
                {
                    "status": "sent",
                    "last_contacted_at": datetime.now(timezone.utc).isoformat(),
                    "chase_count": (chase.get("chase_count") or 0) + 1,
                    "gmail_thread_id": result.get("thread_id") or chase.get("gmail_thread_id"),
                    "safety_level": safety["safety_level"],
                },
            )
            add_event(
                chase_id=chase_id,
                event_type="sent",
                summary=subject,
                gmail_message_id=result.get("message_id"),
                metadata={"safety": safety, "context_quality": context.get("context_quality")},
            )
        else:
            result = create_draft(
                subject=subject,
                body=body,
                to_email=to_email,
                thread_id=chase.get("gmail_thread_id"),
            )
            update_chase(
                chase_id,
                {
                    "status": "drafted",
                    "gmail_thread_id": result.get("thread_id") or chase.get("gmail_thread_id"),
                    "safety_level": safety["safety_level"],
                },
            )
            add_event(
                chase_id=chase_id,
                event_type="drafted",
                summary=subject,
                gmail_draft_id=result.get("draft_id"),
                metadata={
                    "requested_action": action,
                    "safety": safety,
                    "context_quality": context.get("context_quality"),
                },
            )

        log_tool_call(
            tool_name="act_on_chase",
            request_summary=f"{action}:{chase_id}",
            success=True,
            entity_type="relationship_chase",
            entity_id=chase_id,
            action_type="send" if should_send else "write",
        )
        return {
            "requested_action": action,
            "performed_action": "sent" if should_send else "draft_created",
            "mode_note": "Sending was not allowed, so a draft was created."
            if action != "draft" and not should_send
            else None,
            "context": context,
            "safety": safety,
            "gmail": result,
        }
    except Exception as exc:
        log_tool_call(tool_name="act_on_chase", request_summary=f"{action}:{chase_id}", success=False, error=str(exc))
        raise
