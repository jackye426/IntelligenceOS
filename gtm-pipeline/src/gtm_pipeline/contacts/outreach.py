"""Materialize gtm_outreach_contacts from intelligence + people (no network)."""

from __future__ import annotations

import logging
from typing import Any

from gtm_pipeline.contacts.pic import (
    derive_contact_status,
    derive_preferred_channel,
    infer_email_source,
    pick_person_in_charge,
    synthetic_pic_from_cqc,
)
from gtm_pipeline.segments import get_cohort, list_members
from gtm_pipeline.shared.provenance import make_provenance, utc_now_iso
from gtm_pipeline.shared.supabase_client import get_client, supabase_configured

logger = logging.getLogger(__name__)


def _fetch_people_by_clinic() -> dict[str, list[dict[str, Any]]]:
    client = get_client()
    by_clinic: dict[str, list[dict[str, Any]]] = {}
    page = 1000
    offset = 0
    while True:
        batch = (
            client.table("gtm_clinic_people")
            .select(
                "id, clinic_intelligence_id, clinic_account_id, full_name, role, specialty, "
                "email, priority, linkedin_url, linkedin_status, provenance, evidence"
            )
            .range(offset, offset + page - 1)
            .execute()
            .data
            or []
        )
        for p in batch:
            cid = p.get("clinic_intelligence_id")
            if cid:
                by_clinic.setdefault(cid, []).append(p)
        if len(batch) < page:
            break
        offset += page
    return by_clinic


def _cohort_clinic_ids(slug: str) -> set[str] | None:
    if not slug:
        return None
    if not get_cohort(slug):
        raise ValueError(f"Unknown cohort: {slug}")
    members = list_members(slug, status=None, limit=5000)["members"]
    return {m["clinic_intelligence_id"] for m in members if m.get("clinic_intelligence_id")}


def build_contact_payload(
    intel: dict[str, Any],
    people: list[dict[str, Any]],
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build upsert payload for one clinic. Preserves RR fields from existing."""
    ni = (intel.get("cqc_nominated_individual") or "").strip()
    rm = (intel.get("cqc_registered_manager") or "").strip()
    pic = pick_person_in_charge(
        people,
        cqc_nominated_individual=ni,
        cqc_registered_manager=rm,
    )
    if not pic:
        pic = synthetic_pic_from_cqc(
            cqc_nominated_individual=ni,
            cqc_registered_manager=rm,
        )
    if not pic:
        return None

    role = pic.get("_effective_role") or pic.get("role") or "specialist"
    person_id = pic.get("id")
    email = (pic.get("email") or "").strip() or None
    # Prefer existing contact email if already set (manual / RR) over empty person
    if existing and (existing.get("email") or "").strip() and not email:
        email = (existing.get("email") or "").strip()
    email_source = "none"
    if email:
        if existing and (existing.get("email_source") or "") == "rocketreach":
            email_source = "rocketreach"
        elif existing and (existing.get("email_source") or "") == "manual":
            email_source = "manual"
        else:
            email_source = infer_email_source(pic if person_id else None, email)

    linkedin_url = (pic.get("linkedin_url") or "").strip() or None
    linkedin_status = pic.get("linkedin_status")
    if existing and (existing.get("linkedin_url") or "").strip():
        linkedin_url = (existing.get("linkedin_url") or "").strip()
        linkedin_status = existing.get("linkedin_status") or linkedin_status

    rr_email = (existing or {}).get("rocketreach_email")
    rr_status = (existing or {}).get("rocketreach_status") or "none"
    rr_pid = (existing or {}).get("rocketreach_person_id")

    preferred = derive_preferred_channel(email=email, linkedin_url=linkedin_url)
    status = derive_contact_status(
        email=email,
        linkedin_url=linkedin_url,
        rocketreach_status=rr_status,
        linkedin_status=linkedin_status,
    )

    return {
        "clinic_intelligence_id": intel["id"],
        "clinic_account_id": intel.get("clinic_account_id")
        or (pic.get("clinic_account_id") if person_id else None),
        "person_id": person_id,
        "full_name": (pic.get("full_name") or "").strip() or "Unknown",
        "role": role,
        "email": email,
        "email_source": email_source,
        "rocketreach_email": rr_email,
        "rocketreach_status": rr_status,
        "rocketreach_person_id": rr_pid,
        "linkedin_url": linkedin_url,
        "linkedin_status": linkedin_status or ("found" if linkedin_url else "none"),
        "preferred_channel": preferred,
        "priority": int(pic.get("priority") or 50),
        "founder_score": intel.get("founder_score"),
        "status": status,
        "provenance": make_provenance(source="outreach_contacts_refresh", lane="contacts"),
        "updated_at": utc_now_iso(),
    }


def refresh_outreach_contacts(
    *,
    cqc_named_only: bool = True,
    cohort: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Upsert one PIC contact per clinic from SoR. No network."""
    if not supabase_configured():
        raise RuntimeError("Supabase not configured")

    cohort_ids = _cohort_clinic_ids(cohort) if cohort else None
    people_by = _fetch_people_by_clinic()
    client = get_client()

    # Existing contacts for RR/LI preservation
    existing_by: dict[str, dict[str, Any]] = {}
    page = 1000
    offset = 0
    while True:
        batch = (
            client.table("gtm_outreach_contacts")
            .select("*")
            .range(offset, offset + page - 1)
            .execute()
            .data
            or []
        )
        for row in batch:
            existing_by[row["clinic_intelligence_id"]] = row
        if len(batch) < page:
            break
        offset += page

    stats: dict[str, Any] = {
        "scanned": 0,
        "upserted": 0,
        "skipped": 0,
        "ready": 0,
        "needs_enrichment": 0,
        "needs_review": 0,
        "dry_run": dry_run,
        "cqc_named_only": cqc_named_only,
        "cohort": cohort,
    }

    offset = 0
    while True:
        if limit is not None and stats["upserted"] + stats["skipped"] >= limit:
            break
        q = (
            client.table("gtm_clinic_intelligence")
            .select(
                "id, clinic_account_id, clinic_name, founder_score, email, "
                "cqc_location_id, cqc_nominated_individual, cqc_registered_manager"
            )
            .order("founder_score", desc=True)
            .range(offset, offset + page - 1)
        )
        rows = q.execute().data or []
        if not rows:
            break

        payloads: list[dict[str, Any]] = []
        for intel in rows:
            if limit is not None and stats["upserted"] + len(payloads) >= limit:
                break
            stats["scanned"] += 1
            cid = intel["id"]
            if cohort_ids is not None and cid not in cohort_ids:
                continue
            ni = (intel.get("cqc_nominated_individual") or "").strip()
            rm = (intel.get("cqc_registered_manager") or "").strip()
            if cqc_named_only and not ni and not rm:
                stats["skipped"] += 1
                continue
            people = people_by.get(cid) or []
            if not people and not ni and not rm:
                stats["skipped"] += 1
                continue

            payload = build_contact_payload(
                intel, people, existing=existing_by.get(cid)
            )
            if not payload:
                stats["skipped"] += 1
                continue
            # Preserve evidence from existing
            if existing_by.get(cid):
                payload["evidence"] = existing_by[cid].get("evidence") or []
            else:
                payload["evidence"] = []
            payloads.append(payload)
            stats[payload["status"]] = stats.get(payload["status"], 0) + 1

        if dry_run:
            stats["upserted"] += len(payloads)
        else:
            for i in range(0, len(payloads), 100):
                chunk = payloads[i : i + 100]
                client.table("gtm_outreach_contacts").upsert(
                    chunk, on_conflict="clinic_intelligence_id"
                ).execute()
                stats["upserted"] += len(chunk)

        if len(rows) < page:
            break
        offset += page

    return stats


def list_outreach_contacts(
    *,
    status: str | None = None,
    preferred_channel: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    if not supabase_configured():
        raise RuntimeError("Supabase not configured")
    client = get_client()
    count_q = client.table("gtm_outreach_contacts").select("id", count="exact")
    q = (
        client.table("gtm_outreach_contacts")
        .select(
            "id, clinic_intelligence_id, clinic_account_id, person_id, full_name, role, "
            "email, email_source, rocketreach_email, rocketreach_status, linkedin_url, "
            "linkedin_status, preferred_channel, priority, founder_score, status, updated_at"
        )
        .order("founder_score", desc=True)
        .limit(limit)
    )
    if status:
        count_q = count_q.eq("status", status)
        q = q.eq("status", status)
    if preferred_channel:
        count_q = count_q.eq("preferred_channel", preferred_channel)
        q = q.eq("preferred_channel", preferred_channel)
    total = int(count_q.execute().count or 0)
    rows = q.execute().data or []
    return {"contacts": rows, "count": total, "returned": len(rows)}


def list_ready_for_sales(*, limit: int = 200) -> dict[str, Any]:
    """Handoff view: ready contacts with clinic name joined via second query."""
    out = list_outreach_contacts(status="ready", limit=limit)
    if not out["contacts"]:
        return out
    client = get_client()
    ids = [c["clinic_intelligence_id"] for c in out["contacts"]]
    names: dict[str, str] = {}
    for i in range(0, len(ids), 100):
        chunk = ids[i : i + 100]
        rows = (
            client.table("gtm_clinic_intelligence")
            .select("id, clinic_name")
            .in_("id", chunk)
            .execute()
            .data
            or []
        )
        for r in rows:
            names[r["id"]] = r.get("clinic_name") or ""
    for c in out["contacts"]:
        c["clinic_name"] = names.get(c["clinic_intelligence_id"], "")
    return out
