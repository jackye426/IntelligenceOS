"""Practitioner outreach status."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from common.supabase_client import get_client


def get_practitioner_status(practitioner_id: str) -> dict[str, Any]:
    summary = f"practitioner_id={practitioner_id}"
    try:
        outreach = (
            get_client()
            .table("doctor_outreach")
            .select(
                "practitioner_id, canonical_email, normalized_name, status, "
                "followup_stage, last_sent_at, replied_at, last_subject, "
                "whatsapp_tally, last_recommended_at, last_rationale"
            )
            .eq("practitioner_id", practitioner_id)
            .limit(1)
            .execute()
            .data
        )

        if not outreach:
            result = {"practitioner_id": practitioner_id, "found": False}
        else:
            result = {"found": True, **outreach[0]}

        log_tool_call(
            tool_name="get_practitioner_status",
            request_summary=summary,
            success=True,
            entity_type="practitioner",
            entity_id=practitioner_id,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_practitioner_status",
            request_summary=summary,
            success=False,
            entity_type="practitioner",
            entity_id=practitioner_id,
            error=str(exc),
        )
        raise
