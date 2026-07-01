"""Clinic account briefing."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from common.supabase_client import get_client


def get_clinic_briefing(clinic_account_id: str) -> dict[str, Any]:
    summary = f"clinic_account_id={clinic_account_id}"
    try:
        client = get_client()
        account = (
            client.table("clinic_accounts")
            .select(
                "id, name, website_url, pipeline_stage, fit_score, sales_angle, "
                "next_action, next_action_due_at"
            )
            .eq("id", clinic_account_id)
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
            .data
        )
        if not account:
            result = {"clinic_account_id": clinic_account_id, "found": False}
            log_tool_call(
                tool_name="get_clinic_briefing",
                request_summary=summary,
                success=True,
                entity_type="clinic_account",
                entity_id=clinic_account_id,
            )
            return result

        observations = (
            client.table("clinic_observations")
            .select("category, text, confidence, review_status")
            .eq("clinic_account_id", clinic_account_id)
            .eq("review_status", "approved")
            .limit(12)
            .execute()
            .data
            or []
        )
        contacts = (
            client.table("clinic_contacts")
            .select("name, role, email, phone, review_status")
            .eq("clinic_account_id", clinic_account_id)
            .limit(10)
            .execute()
            .data
            or []
        )

        result = {
            "found": True,
            "account": account[0],
            "approved_observations": observations,
            "contacts": contacts,
        }
        log_tool_call(
            tool_name="get_clinic_briefing",
            request_summary=summary,
            success=True,
            entity_type="clinic_account",
            entity_id=clinic_account_id,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_clinic_briefing",
            request_summary=summary,
            success=False,
            entity_type="clinic_account",
            entity_id=clinic_account_id,
            error=str(exc),
        )
        raise
