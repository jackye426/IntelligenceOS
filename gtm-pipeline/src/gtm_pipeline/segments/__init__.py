"""Outreach cohort refresh from existing Doctify clinic profile + people."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from gtm_pipeline.segments.specialty import (
    clinic_specialty_keys,
    primary_specialty_label,
)
from gtm_pipeline.shared.supabase_client import get_client, supabase_configured

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def list_cohorts(*, active_only: bool = True) -> list[dict[str, Any]]:
    if not supabase_configured():
        return []
    q = get_client().table("gtm_outreach_cohorts").select("*").order("priority", desc=True)
    if active_only:
        q = q.eq("active", True)
    return q.execute().data or []


def get_cohort(slug: str) -> dict[str, Any] | None:
    rows = (
        get_client()
        .table("gtm_outreach_cohorts")
        .select("*")
        .eq("slug", slug)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def list_members(
    slug: str,
    *,
    status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    cohort = get_cohort(slug)
    if not cohort:
        raise ValueError(f"Unknown cohort slug: {slug}")
    client = get_client()
    count_q = (
        client.table("gtm_outreach_cohort_members")
        .select("id", count="exact")
        .eq("cohort_id", cohort["id"])
    )
    if status:
        count_q = count_q.eq("status", status)
    count_res = count_q.execute()
    total = int(count_res.count or 0)

    q = (
        client.table("gtm_outreach_cohort_members")
        .select("*")
        .eq("cohort_id", cohort["id"])
        .order("founder_score", desc=True)
        .limit(limit)
    )
    if status:
        q = q.eq("status", status)
    rows = q.execute().data or []
    return {"cohort": cohort, "members": rows, "count": total, "returned": len(rows)}


def _fetch_people_index() -> tuple[dict[str, list[dict[str, Any]]], set[str]]:
    """clinic_intelligence_id -> people rows; set of ids with any email."""
    client = get_client()
    by_clinic: dict[str, list[dict[str, Any]]] = {}
    with_email: set[str] = set()
    page = 1000
    offset = 0
    while True:
        batch = (
            client.table("gtm_clinic_people")
            .select(
                "id, clinic_intelligence_id, full_name, role, specialty, email, priority, "
                "linkedin_url, linkedin_status"
            )
            .range(offset, offset + page - 1)
            .execute()
            .data
            or []
        )
        for p in batch:
            cid = p.get("clinic_intelligence_id")
            if not cid:
                continue
            by_clinic.setdefault(cid, []).append(p)
            if (p.get("email") or "").strip():
                with_email.add(cid)
        if len(batch) < page:
            break
        offset += page
    return by_clinic, with_email


def _pick_best_person(
    people: list[dict[str, Any]],
    *,
    preferred_specialty_keys: set[str],
    cqc_nominated_individual: str = "",
    cqc_registered_manager: str = "",
) -> dict[str, Any] | None:
    """PIC order: NI → RM → founder/high-priority (aligned with outreach contacts)."""
    from gtm_pipeline.contacts.pic import pick_person_in_charge

    if not people:
        return None
    pic = pick_person_in_charge(
        people,
        cqc_nominated_individual=cqc_nominated_individual,
        cqc_registered_manager=cqc_registered_manager,
    )
    if pic:
        return pic
    # Fallback: specialty overlap then priority
    def score(p: dict[str, Any]) -> tuple:
        spec_keys = clinic_specialty_keys([p.get("specialty") or ""])
        spec_hit = 1 if (spec_keys & preferred_specialty_keys) else 0
        return (spec_hit, int(p.get("priority") or 0))

    return max(people, key=score)


def _member_status(
    *,
    has_email: bool,
    best: dict[str, Any] | None,
) -> str:
    if has_email:
        return "ready"
    if best and (best.get("linkedin_url") or "").strip():
        return "found_linkedin"
    return "needs_contact"


def refresh_cohort(slug: str, *, dry_run: bool = False) -> dict[str, Any]:
    """Rebuild membership for one cohort from current intelligence + people."""
    if not supabase_configured():
        raise RuntimeError("Supabase not configured")

    cohort = get_cohort(slug)
    if not cohort:
        raise ValueError(f"Unknown cohort slug: {slug}")

    rules = cohort.get("rules") or {}
    sizes = rules.get("sizes")
    size_set = set(sizes) if sizes else None
    specialty_keys = set(rules.get("specialty_keys") or [])
    require_people = bool(rules.get("require_people", True))
    min_founder = rules.get("min_founder_score")
    require_no_email = bool(rules.get("require_no_person_email", False))
    require_cqc = rules.get("require_cqc")  # True / False / None

    people_by_clinic, email_clinics = _fetch_people_index()
    client = get_client()

    matched: list[dict[str, Any]] = []
    page = 1000
    offset = 0
    scanned = 0

    while True:
        batch = (
            client.table("gtm_clinic_intelligence")
            .select(
                "id, clinic_name, visible_clinic_size, specialties, cqc_specialisms, "
                "founder_score, cqc_location_id, cqc_nominated_individual, cqc_registered_manager"
            )
            .range(offset, offset + page - 1)
            .execute()
            .data
            or []
        )
        for row in batch:
            scanned += 1
            cid = row["id"]
            people = people_by_clinic.get(cid) or []
            if require_people and not people:
                continue

            size = row.get("visible_clinic_size") or "unknown"
            if size_set is not None and size not in size_set:
                continue

            people_specs = [p.get("specialty") or "" for p in people]
            keys = clinic_specialty_keys(
                row.get("specialties"),
                row.get("cqc_specialisms"),
                people_specs,
            )
            if specialty_keys and not (keys & specialty_keys):
                continue

            score = int(row.get("founder_score") or 0)
            if min_founder is not None and score < int(min_founder):
                continue

            has_cqc = bool(row.get("cqc_location_id"))
            if require_cqc is True and not has_cqc:
                continue
            if require_cqc is False and has_cqc:
                continue

            has_email = cid in email_clinics
            if require_no_email and has_email:
                continue

            best = _pick_best_person(
                people,
                preferred_specialty_keys=specialty_keys,
                cqc_nominated_individual=row.get("cqc_nominated_individual") or "",
                cqc_registered_manager=row.get("cqc_registered_manager") or "",
            )
            status = _member_status(has_email=has_email, best=best)
            primary = primary_specialty_label(
                list(row.get("specialties") or [])
                or [p.get("specialty") for p in people if p.get("specialty")],
                preferred_keys=specialty_keys or None,
            )
            matched.append(
                {
                    "cohort_id": cohort["id"],
                    "clinic_intelligence_id": cid,
                    "primary_specialty": primary or None,
                    "visible_clinic_size": size,
                    "has_person_email": has_email,
                    "best_person_id": (best or {}).get("id"),
                    "founder_score": score,
                    "status": status,
                    "reasons": [
                        {"specialty_keys": sorted(keys & specialty_keys)}
                        if specialty_keys
                        else {"specialty_keys": sorted(keys)[:8]}
                    ],
                    "updated_at": _now(),
                }
            )

        if len(batch) < page:
            break
        offset += page

    status_counts: dict[str, int] = {}
    for m in matched:
        status_counts[m["status"]] = status_counts.get(m["status"], 0) + 1

    if dry_run:
        return {
            "slug": slug,
            "dry_run": True,
            "scanned": scanned,
            "matched": len(matched),
            "status_counts": status_counts,
        }

    # Replace membership for this cohort
    client.table("gtm_outreach_cohort_members").delete().eq(
        "cohort_id", cohort["id"]
    ).execute()

    for i in range(0, len(matched), 200):
        chunk = matched[i : i + 200]
        client.table("gtm_outreach_cohort_members").insert(chunk).execute()

    client.table("gtm_outreach_cohorts").update({"updated_at": _now()}).eq(
        "id", cohort["id"]
    ).execute()

    return {
        "slug": slug,
        "dry_run": False,
        "scanned": scanned,
        "matched": len(matched),
        "status_counts": status_counts,
    }


def refresh_all_cohorts(*, dry_run: bool = False) -> dict[str, Any]:
    results = []
    for c in list_cohorts(active_only=True):
        results.append(refresh_cohort(c["slug"], dry_run=dry_run))
    return {"cohorts": results}
