"""Thin GTM sales wrap. Corpus tools are not a substitute for this list."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from common.supabase_client import get_client

HARD_CAP = 100
DEFAULT_LIMIT = 50


class GtmSalesError(ValueError):
    """Bad arguments for the GTM sales wrap."""


def _limit(limit: int | None) -> int:
    value = DEFAULT_LIMIT if limit is None else int(limit)
    if value < 1:
        raise GtmSalesError("limit must be >= 1")
    return min(value, HARD_CAP)


def list_gtm_ready_for_sales(
    cohort: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Wrap list_ready_for_sales. Never drafts mail. Cap 100."""
    cap = _limit(limit)
    try:
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        gtm_src = str(root / "gtm-pipeline" / "src")
        if gtm_src not in sys.path:
            sys.path.insert(0, gtm_src)
        from gtm_pipeline.contacts.outreach import list_ready_for_sales
    except ImportError as exc:
        raise GtmSalesError(f"gtm-pipeline is not importable: {exc}") from exc

    out = list_ready_for_sales(limit=cap, cohort=cohort or None)
    log_tool_call(
        tool_name="list_gtm_ready_for_sales",
        request_summary=f"cohort={cohort} limit={cap}",
        success=True,
        entity_type="gtm_outreach_contacts",
    )
    return out


def get_gtm_contact(clinic_intelligence_id: str) -> dict[str, Any]:
    """Clinic + person + contact + TikTok angle. No draft."""
    cid = (clinic_intelligence_id or "").strip()
    if not cid:
        raise GtmSalesError("clinic_intelligence_id is required")
    client = get_client()
    clinics = (
        client.table("gtm_clinic_intelligence")
        .select(
            "id, clinic_name, website_url, specialties, source_creator_profile_id, "
            "email, visible_clinic_size, evidence, provenance"
        )
        .eq("id", cid)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not clinics:
        raise GtmSalesError(f"unknown clinic_intelligence_id {cid}")
    clinic = clinics[0]
    people = (
        client.table("gtm_clinic_people")
        .select(
            "id, full_name, role, specialty, email, creator_profile_id, social_profiles, priority"
        )
        .eq("clinic_intelligence_id", cid)
        .execute()
        .data
        or []
    )
    contacts = (
        client.table("gtm_outreach_contacts")
        .select(
            "id, full_name, role, email, email_source, status, preferred_channel, "
            "linkedin_url, evidence, provenance, person_id"
        )
        .eq("clinic_intelligence_id", cid)
        .limit(1)
        .execute()
        .data
        or []
    )
    contact = contacts[0] if contacts else None
    evidence = (contact or {}).get("evidence") or clinic.get("evidence") or []
    angle = next(
        (item for item in evidence if isinstance(item, dict) and item.get("kind") == "tiktok_creator_angle"),
        None,
    )
    log_tool_call(
        tool_name="get_gtm_contact",
        request_summary=f"clinic={cid}",
        success=True,
        entity_type="gtm_clinic_intelligence",
        entity_id=cid,
    )
    return {
        "clinic": clinic,
        "people": people,
        "contact": contact,
        "tiktok_creator_angle": angle,
        "ready": bool(contact and contact.get("status") == "ready"),
        "note": "Draft only via draft_outreach_email after confirmed=true. Never mail from this tool.",
    }
