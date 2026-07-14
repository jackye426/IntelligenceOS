"""Upsert gtm_clinic_intelligence / gtm_clinic_people / clinic_accounts links."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from gtm_pipeline.shared.supabase_client import get_client, supabase_configured

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _doctify_key(url: str) -> str:
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
    except ValueError:
        return url.rstrip("/")
    return (parsed.netloc.lower().removeprefix("www.") + parsed.path).rstrip("/")


def find_or_create_clinic_account(
    *,
    name: str,
    doctify_url: str = "",
    website_url: str = "",
    dry_run: bool = False,
) -> str | None:
    """Link to existing clinic_accounts by Doctify URL or name; insert if missing."""
    if not supabase_configured():
        return None
    client = get_client()

    if doctify_url:
        # clinic_accounts.website_url often stores the Doctify profile URL
        rows = (
            client.table("clinic_accounts")
            .select("id, website_url, name")
            .ilike("website_url", f"%{urlparse(doctify_url).path.rstrip('/')}%")
            .limit(5)
            .execute()
            .data
            or []
        )
        key = _doctify_key(doctify_url)
        for row in rows:
            if _doctify_key(row.get("website_url") or "") == key:
                return row["id"]

    if name:
        rows = (
            client.table("clinic_accounts")
            .select("id, name")
            .ilike("name", name)
            .limit(5)
            .execute()
            .data
            or []
        )
        for row in rows:
            if (row.get("name") or "").lower() == name.lower():
                return row["id"]
        if len(rows) == 1:
            return rows[0]["id"]

    if dry_run:
        logger.info("[dry-run] would create clinic_account name=%s url=%s", name, doctify_url)
        return None

    website = doctify_url or website_url or f"https://unknown.invalid/{name}"
    inserted = (
        client.table("clinic_accounts")
        .insert({"name": name or "Unknown clinic", "website_url": website})
        .execute()
        .data
        or []
    )
    return inserted[0]["id"] if inserted else None


def upsert_clinic_intelligence(row: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    """Upsert gtm_clinic_intelligence by doctify_url (preferred) or clinic_account_id."""
    payload = {**row, "updated_at": _now()}
    payload.setdefault("scraped_at", _now())

    if dry_run or not supabase_configured():
        logger.info(
            "[dry-run] would upsert gtm_clinic_intelligence doctify=%s name=%s",
            payload.get("doctify_url"),
            payload.get("clinic_name"),
        )
        return {"dry_run": True, "payload": payload}

    client = get_client()
    doctify_url = payload.get("doctify_url")
    account_id = payload.get("clinic_account_id")

    existing = None
    if doctify_url:
        found = (
            client.table("gtm_clinic_intelligence")
            .select("id")
            .eq("doctify_url", doctify_url)
            .limit(1)
            .execute()
            .data
            or []
        )
        existing = found[0] if found else None
    if existing is None and account_id:
        found = (
            client.table("gtm_clinic_intelligence")
            .select("id")
            .eq("clinic_account_id", account_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        existing = found[0] if found else None

    if existing:
        updated = (
            client.table("gtm_clinic_intelligence")
            .update(payload)
            .eq("id", existing["id"])
            .execute()
            .data
            or []
        )
        return updated[0] if updated else {"id": existing["id"], **payload}

    inserted = client.table("gtm_clinic_intelligence").insert(payload).execute().data or []
    return inserted[0] if inserted else payload


def upsert_clinic_people(
    clinic_intelligence_id: str,
    people: list[dict[str, Any]],
    *,
    clinic_account_id: str | None = None,
    dry_run: bool = False,
) -> int:
    if dry_run or not supabase_configured():
        logger.info("[dry-run] would upsert %d gtm_clinic_people", len(people))
        return len(people)

    client = get_client()
    n = 0
    for person in people:
        payload = {
            **person,
            "clinic_intelligence_id": clinic_intelligence_id,
            "updated_at": _now(),
        }
        if clinic_account_id:
            payload["clinic_account_id"] = clinic_account_id

        doctify_profile = payload.get("doctify_profile_url")
        if doctify_profile:
            existing = (
                client.table("gtm_clinic_people")
                .select("id")
                .eq("clinic_intelligence_id", clinic_intelligence_id)
                .eq("doctify_profile_url", doctify_profile)
                .limit(1)
                .execute()
                .data
                or []
            )
            if existing:
                client.table("gtm_clinic_people").update(payload).eq("id", existing[0]["id"]).execute()
                n += 1
                continue

        client.table("gtm_clinic_people").insert(payload).execute()
        n += 1
    return n


def attach_owner_evidence(
    *,
    clinic_account_id: str,
    person_name: str,
    role: str,
    email: str = "",
    evidence: list[dict[str, Any]] | None = None,
    provenance: dict[str, Any] | None = None,
    reasons: list[str] | None = None,
) -> None:
    client = get_client()
    intel_rows = (
        client.table("gtm_clinic_intelligence")
        .select("id, evidence, leadership_keywords")
        .eq("clinic_account_id", clinic_account_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if intel_rows:
        intel = intel_rows[0]
        merged_evidence = list(intel.get("evidence") or []) + list(evidence or [])
        keywords = list(
            dict.fromkeys(list(intel.get("leadership_keywords") or []) + list(reasons or []))
        )
        client.table("gtm_clinic_intelligence").update(
            {
                "evidence": merged_evidence,
                "leadership_keywords": keywords,
                "updated_at": _now(),
            }
        ).eq("id", intel["id"]).execute()
        intel_id = intel["id"]
    else:
        inserted = (
            client.table("gtm_clinic_intelligence")
            .insert(
                {
                    "clinic_account_id": clinic_account_id,
                    "evidence": evidence or [],
                    "leadership_keywords": reasons or [],
                    "provenance": provenance or {},
                    "scraped_at": _now(),
                }
            )
            .execute()
            .data
            or []
        )
        intel_id = inserted[0]["id"] if inserted else None

    if not intel_id:
        return

    client.table("gtm_clinic_people").insert(
        {
            "clinic_intelligence_id": intel_id,
            "clinic_account_id": clinic_account_id,
            "full_name": person_name,
            "role": role,
            "email": email or None,
            "priority": 80,
            "reasons": reasons or [],
            "evidence": evidence or [],
            "provenance": provenance or {},
        }
    ).execute()


def sync_doctify_extract(extract: Any, *, dry_run: bool = False, create_account: bool = True) -> dict[str, Any]:
    """Persist a DoctifyPracticeExtract to Supabase."""
    from gtm_pipeline.doctify.extract import DoctifyPracticeExtract

    assert isinstance(extract, DoctifyPracticeExtract)

    account_id = None
    if create_account:
        account_id = find_or_create_clinic_account(
            name=extract.clinic_name,
            doctify_url=extract.doctify_url,
            website_url=extract.website_url,
            dry_run=dry_run,
        )

    intel_payload = {
        "clinic_account_id": account_id,
        "doctify_url": extract.doctify_url,
        "clinic_name": extract.clinic_name,
        "website_url": extract.website_url or None,
        "email": extract.email or None,
        "phone": extract.phone or None,
        "address": extract.address or None,
        "postcode": extract.postcode or None,
        "bio": extract.bio or None,
        "specialties": extract.specialties,
        "listed_specialist_count": extract.listed_specialist_count,
        "visible_clinic_size": extract.visible_clinic_size,
        "founder_score": extract.founder_score,
        "structure": extract.structure,
        "leadership_keywords": extract.leadership_keywords,
        "evidence": extract.evidence,
        "provenance": extract.provenance,
    }
    intel = upsert_clinic_intelligence(intel_payload, dry_run=dry_run)

    people = [
        {
            "full_name": s.name,
            "role": "specialist",
            "specialty": s.specialty or None,
            "doctify_profile_url": s.profile_url or None,
            "priority": 40,
            "reasons": ["doctify_specialist_card"],
            "provenance": extract.provenance,
        }
        for s in extract.specialists
    ]
    people_n = 0
    if intel.get("id") and not dry_run:
        people_n = upsert_clinic_people(
            intel["id"], people, clinic_account_id=account_id, dry_run=dry_run
        )
    elif dry_run:
        people_n = len(people)

    return {
        "clinic_account_id": account_id,
        "clinic_intelligence_id": intel.get("id"),
        "people_upserted": people_n,
        "dry_run": dry_run or not supabase_configured(),
    }
