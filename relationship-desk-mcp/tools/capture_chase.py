"""Capture a new chase from minimal direction."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from common.relationship_store import create_chase, resolve_contact_hint


def run(
    *,
    instruction: str,
    contact_hint: str | None = None,
    email: str | None = None,
    objective: str | None = None,
    why_it_matters: str | None = None,
    needed_response: str | None = None,
    next_chase_due_at: str | None = None,
    gmail_thread_id: str | None = None,
    send_mode: str = "requires_approval",
) -> dict[str, Any]:
    try:
        contact_resolution = resolve_contact_hint(contact_hint or instruction, email=email)
        chase = create_chase(
            objective=objective or instruction,
            contact_hint=contact_hint,
            email=email,
            gmail_thread_id=gmail_thread_id,
            why_it_matters=why_it_matters,
            needed_response=needed_response,
            next_chase_due_at=next_chase_due_at,
            send_mode=send_mode,
            metadata={"source_instruction": instruction, "contact_resolution": contact_resolution},
        )
        log_tool_call(
            tool_name="capture_chase",
            request_summary=instruction,
            success=True,
            entity_type="relationship_chase",
            entity_id=chase["id"],
            action_type="write",
        )
        return {
            "chase": chase,
            "contact_resolution": contact_resolution,
            "next_step": "Use draft_chase or act_on_chase when ready.",
        }
    except Exception as exc:
        log_tool_call(tool_name="capture_chase", request_summary=instruction, success=False, error=str(exc))
        raise
