"""Apply RocketReach results to gtm_outreach_contacts (+ optional people mirror)."""

from __future__ import annotations

import logging
import time
from typing import Any

from gtm_pipeline import config
from gtm_pipeline.contacts.pic import derive_contact_status, derive_preferred_channel
from gtm_pipeline.rocketreach.client import lookup_person
from gtm_pipeline.segments import get_cohort, list_members
from gtm_pipeline.shared.provenance import evidence_item, make_provenance, utc_now_iso
from gtm_pipeline.shared.supabase_client import get_client, supabase_configured
from gtm_pipeline.sync.match_reviews import maybe_queue_match_review

logger = logging.getLogger(__name__)


def apply_rocketreach_result(
    contact: dict[str, Any],
    result: dict[str, Any],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Persist RR result. Always store rocketreach_*; only set email if empty or RR higher."""
    status = result.get("status") or "none"
    entry = {
        "contact_id": contact.get("id"),
        "full_name": contact.get("full_name"),
        "status": status,
        "email": result.get("email") or "",
        "confidence": result.get("confidence") or 0,
    }
    if status == "skipped" or dry_run or not supabase_configured():
        return entry

    client = get_client()
    existing_email = (contact.get("email") or "").strip()
    rr_email = (result.get("email") or "").strip() or None
    conf = float(result.get("confidence") or 0)

    email = existing_email or None
    email_source = contact.get("email_source") or "none"
    # Promote RR email when we have none, or when source is none and conf high
    if rr_email and status == "found" and conf >= config.MATCH_AUTO_ACCEPT:
        if not existing_email:
            email = rr_email
            email_source = "rocketreach"
        # If we already have email, keep it; still store rocketreach_email

    li_url = (contact.get("linkedin_url") or "").strip() or None
    rr_li = (result.get("linkedin_url") or "").strip()
    linkedin_status = contact.get("linkedin_status")
    if rr_li and not li_url:
        li_url = rr_li
        linkedin_status = "found"

    preferred = derive_preferred_channel(email=email, linkedin_url=li_url)
    new_status = derive_contact_status(
        email=email,
        linkedin_url=li_url,
        rocketreach_status=status,
        linkedin_status=linkedin_status,
    )

    ev = list(contact.get("evidence") or [])
    ev.append(
        evidence_item(
            kind="rocketreach_lookup",
            value={
                "status": status,
                "email": rr_email,
                "confidence": conf,
                "rocketreach_id": result.get("rocketreach_id"),
                "emails": (result.get("emails") or [])[:5],
            },
            source="rocketreach",
            confidence=conf,
        )
    )

    payload = {
        "rocketreach_email": rr_email,
        "rocketreach_status": status,
        "rocketreach_person_id": str(result.get("rocketreach_id") or "") or None,
        "email": email,
        "email_source": email_source if email else "none",
        "linkedin_url": li_url,
        "linkedin_status": linkedin_status or ("found" if li_url else contact.get("linkedin_status")),
        "preferred_channel": preferred,
        "status": new_status,
        "evidence": ev,
        "provenance": make_provenance(source="rocketreach", lane="contacts"),
        "updated_at": utc_now_iso(),
    }
    client.table("gtm_outreach_contacts").update(payload).eq("id", contact["id"]).execute()

    # Mirror email onto people PIC when we filled a gap
    person_id = contact.get("person_id")
    if person_id and email and email_source == "rocketreach" and not existing_email:
        client.table("gtm_clinic_people").update(
            {
                "email": email,
                "updated_at": utc_now_iso(),
                "provenance": make_provenance(source="rocketreach", lane="contacts"),
            }
        ).eq("id", person_id).execute()

    if status == "ambiguous":
        maybe_queue_match_review(
            entity_type="person_clinic",
            candidate={
                "rocketreach_emails": result.get("emails"),
                "picked": rr_email,
                "name": contact.get("full_name"),
            },
            target={
                "contact_id": contact.get("id"),
                "clinic_intelligence_id": contact.get("clinic_intelligence_id"),
                "person_id": person_id,
            },
            confidence=max(conf, config.MATCH_REVIEW_THRESHOLD),
            reasons=["rocketreach_ambiguous"],
            clinic_intelligence_id=contact.get("clinic_intelligence_id"),
            clinic_account_id=contact.get("clinic_account_id"),
            dedupe_key=f"person_clinic:{contact.get('id')}:rocketreach",
            dry_run=False,
        )

    entry["preferred_channel"] = preferred
    entry["contact_status"] = new_status
    return entry


def enrich_contact_rocketreach(
    contact: dict[str, Any],
    *,
    clinic_name: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    result = lookup_person(
        contact.get("full_name") or "",
        current_employer=clinic_name,
        linkedin_url=contact.get("linkedin_url") or "",
    )
    return apply_rocketreach_result(contact, result, dry_run=dry_run)


def _load_contacts_for_enrich(
    *,
    cohort: str | None,
    limit: int,
    force: bool,
) -> list[dict[str, Any]]:
    client = get_client()
    clinic_filter: set[str] | None = None
    if cohort:
        if not get_cohort(cohort):
            raise ValueError(f"Unknown cohort: {cohort}")
        members = list_members(cohort, limit=5000)["members"]
        clinic_filter = {
            m["clinic_intelligence_id"] for m in members if m.get("clinic_intelligence_id")
        }

    q = (
        client.table("gtm_outreach_contacts")
        .select("*")
        .order("founder_score", desc=True)
        .limit(max(limit * 5, limit))
    )
    rows = q.execute().data or []
    out: list[dict[str, Any]] = []
    for row in rows:
        if clinic_filter is not None and row["clinic_intelligence_id"] not in clinic_filter:
            continue
        st = (row.get("rocketreach_status") or "none").lower()
        if not force and st in {"found", "ambiguous"}:
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def rocketreach_enrich_contacts(
    *,
    limit: int = 20,
    cohort: str | None = None,
    delay_s: float = 1.0,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Sync RocketReach enrich for outreach contacts (everyone — not email-gap-only)."""
    if not supabase_configured():
        raise RuntimeError("Supabase not configured")

    contacts = _load_contacts_for_enrich(cohort=cohort, limit=limit, force=force)
    client = get_client()
    stats: dict[str, Any] = {
        "attempted": 0,
        "found": 0,
        "ambiguous": 0,
        "none": 0,
        "failed": 0,
        "skipped": 0,
        "dry_run": dry_run,
        "cohort": cohort,
        "items": [],
    }

    for contact in contacts:
        intel = (
            client.table("gtm_clinic_intelligence")
            .select("clinic_name")
            .eq("id", contact["clinic_intelligence_id"])
            .limit(1)
            .execute()
            .data
            or []
        )
        clinic_name = (intel[0].get("clinic_name") if intel else "") or ""
        stats["attempted"] += 1
        entry = enrich_contact_rocketreach(
            contact, clinic_name=clinic_name, dry_run=dry_run
        )
        st = entry.get("status") or "none"
        stats[st] = stats.get(st, 0) + 1
        stats["items"].append(entry)
        if delay_s:
            time.sleep(delay_s)

    return stats


def enqueue_rocketreach_durable(
    *,
    limit: int = 20,
    cohort: str | None = None,
    delay_s: float = 1.0,
    dry_run: bool = False,
    force: bool = False,
    start_worker: bool = True,
    concurrency: int | None = 1,
) -> dict[str, Any]:
    from gtm_pipeline.durable_jobs import create_job, start_durable_job_async

    contacts = _load_contacts_for_enrich(cohort=cohort, limit=limit, force=force)
    client = get_client()
    job_items: list[dict[str, Any]] = []
    for c in contacts:
        intel = (
            client.table("gtm_clinic_intelligence")
            .select("clinic_name")
            .eq("id", c["clinic_intelligence_id"])
            .limit(1)
            .execute()
            .data
            or []
        )
        job_items.append(
            {
                "item_key": c["id"],
                "payload": {
                    "contact_id": c["id"],
                    "clinic_name": (intel[0].get("clinic_name") if intel else "") or "",
                },
            }
        )

    params = {
        "cohort": cohort,
        "limit": limit,
        "delay_s": delay_s,
        "dry_run": dry_run,
        "force": force,
    }
    job = create_job(
        "rocketreach_enrich",
        params=params,
        meta={"item_count": len(job_items), "cohort": cohort},
        items=job_items,
    )
    job_id = job["id"]

    def _handler(item_row: dict[str, Any]) -> dict[str, Any]:
        return rocketreach_item_handler(
            item_row, dry_run=dry_run, delay_s=delay_s
        )

    if start_worker and job_items:
        start_durable_job_async(job_id, _handler, concurrency=concurrency or 1)

    return {
        "job_id": job_id,
        "status": "queued",
        "durable": True,
        "poll": f"/jobs/{job_id}",
        "total_items": len(job_items),
        "cohort": cohort,
    }


def rocketreach_item_handler(
    item_row: dict[str, Any],
    *,
    dry_run: bool = False,
    delay_s: float = 0.0,
) -> dict[str, Any]:
    payload = item_row.get("payload") or {}
    client = get_client()
    rows = (
        client.table("gtm_outreach_contacts")
        .select("*")
        .eq("id", payload["contact_id"])
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return {"error": "contact_not_found", "contact_id": payload.get("contact_id")}
    out = enrich_contact_rocketreach(
        rows[0],
        clinic_name=payload.get("clinic_name") or "",
        dry_run=dry_run,
    )
    if delay_s:
        time.sleep(delay_s)
    return out
