"""Appointment availability lookup."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from common.audit import log_tool_call
from common.supabase_client import get_client


def get_appointment_availability(
    practitioner_name: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    summary = f"practitioner_name={practitioner_name}, limit={limit}"
    try:
        query = (
            get_client()
            .table("appointment_slots")
            .select(
                "practitioner_name, location, specialty, starts_at, ends_at, "
                "status, booking_url, last_seen_at"
            )
            .eq("status", "visible")
            .gte("starts_at", datetime.now(timezone.utc).isoformat())
            .order("starts_at")
            .limit(limit)
        )
        if practitioner_name:
            query = query.ilike("practitioner_name", f"%{practitioner_name}%")

        rows = query.execute().data or []
        log_tool_call(
            tool_name="get_appointment_availability",
            request_summary=summary,
            success=True,
        )
        return rows
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_appointment_availability",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise
