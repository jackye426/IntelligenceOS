"""Weekly operational briefing across key intelligence tables."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from common.supabase_client import get_client


def get_weekly_briefing() -> dict[str, Any]:
    summary = "weekly_briefing"
    try:
        client = get_client()

        active_clinics = (
            client.table("clinic_accounts")
            .select("id", count="exact")
            .is_("deleted_at", "null")
            .neq("pipeline_stage", "Lost")
            .execute()
        )
        outreach_due = (
            client.table("doctor_outreach")
            .select("practitioner_id, status, followup_stage, last_sent_at")
            .eq("status", "active")
            .order("last_sent_at")
            .limit(10)
            .execute()
            .data
            or []
        )
        top_content = (
            client.table("content_posts")
            .select("platform, title, topic, metrics, posted_at")
            .order("posted_at", desc=True)
            .limit(5)
            .execute()
            .data
            or []
        )
        upcoming_slots = (
            client.table("appointment_slots")
            .select("practitioner_name, location, starts_at, status")
            .eq("status", "visible")
            .order("starts_at")
            .limit(5)
            .execute()
            .data
            or []
        )
        recent_runs = (
            client.table("data_ingestion_runs")
            .select("job_name, status, started_at, rows_inserted, rows_updated, error")
            .order("started_at", desc=True)
            .limit(5)
            .execute()
            .data
            or []
        )

        result = {
            "active_clinic_count": active_clinics.count or 0,
            "active_outreach_targets": outreach_due,
            "recent_content": top_content,
            "upcoming_appointment_slots": upcoming_slots,
            "recent_ingestion_runs": recent_runs,
        }
        log_tool_call(tool_name="get_weekly_briefing", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_weekly_briefing",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise
