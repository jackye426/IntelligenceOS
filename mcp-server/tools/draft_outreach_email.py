"""Create a Gmail draft for human review (never sends)."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from common.gmail_draft import create_gmail_draft


def draft_outreach_email(
    *,
    subject: str,
    body: str,
    to_email: str | None = None,
    confirmed: bool = False,
    practitioner_id: str | None = None,
) -> dict[str, Any]:
    if not confirmed:
        raise ValueError(
            "draft_outreach_email requires confirmed=true after human review of subject and body"
        )
    if not subject.strip() or not body.strip():
        raise ValueError("subject and body are required")

    summary = f"to={to_email or 'blank'} practitioner_id={practitioner_id}"
    try:
        draft = create_gmail_draft(subject=subject.strip(), body=body.strip(), to_email=to_email)
        log_tool_call(
            tool_name="draft_outreach_email",
            request_summary=summary,
            success=True,
            action_type="write",
            entity_type="practitioner",
            entity_id=practitioner_id,
            metadata={"draft_id": draft.get("draft_id"), "to_email": to_email},
        )
        return {
            **draft,
            "practitioner_id": practitioner_id,
            "note": "Draft created in Gmail. Human must review and send manually.",
        }
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="draft_outreach_email",
            request_summary=summary,
            success=False,
            action_type="write",
            error=str(exc),
        )
        raise
