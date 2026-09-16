"""Promote confirmed UK creator customers into the existing GTM sales path.

Never creates clinic_accounts. Identity writes go through upsert_clinic_intelligence
and upsert_clinic_people, then refresh_cohort / refresh_outreach_contacts.
"""

from __future__ import annotations

import logging
from typing import Any

from gtm_pipeline.contacts.outreach import refresh_outreach_contacts
from gtm_pipeline.creators.link import host_of
from gtm_pipeline.creators.paging import fetch_all
from gtm_pipeline.segments import refresh_cohort
from gtm_pipeline.shared.name import person_name_key
from gtm_pipeline.shared.provenance import evidence_item, make_provenance
from gtm_pipeline.shared.supabase_client import get_client, supabase_configured
from gtm_pipeline.sync.clinic_intelligence import upsert_clinic_intelligence, upsert_clinic_people

logger = logging.getLogger(__name__)

COHORT = "tiktok_doctor_creators"
PROVENANCE_SOURCE = "creator_corpus"
PROVENANCE_LANE = "tiktok_creator"


def _display_name(profile: dict[str, Any]) -> str:
    nick = (profile.get("nickname") or "").strip()
    if nick:
        return nick
    handle = (profile.get("handle") or "").strip()
    return f"@{handle}" if handle else "Unknown doctor"


def _clinic_name(profile: dict[str, Any]) -> str:
    for item in profile.get("bio_links") or []:
        if isinstance(item, dict) and item.get("class") == "own_site":
            host = host_of(item.get("url"))
            if host:
                label = host.split(".")[0].replace("-", " ").title()
                if label:
                    return label
    return f"{_display_name(profile)} — private practice"


def _own_site_url(profile: dict[str, Any]) -> str | None:
    for item in profile.get("bio_links") or []:
        if isinstance(item, dict) and item.get("class") == "own_site" and item.get("url"):
            return str(item["url"])
    return None


def _bio_email(profile: dict[str, Any]) -> str | None:
    emails = [e for e in (profile.get("bio_emails") or []) if e]
    return emails[0] if emails else None


def _social_profiles(profile: dict[str, Any]) -> dict[str, str]:
    handles = profile.get("bio_handles") or {}
    out: dict[str, str] = {"tiktok": profile.get("handle") or ""}
    if isinstance(handles, dict):
        for key, value in handles.items():
            if value:
                out[str(key)] = str(value)
    return {k: v for k, v in out.items() if v}


def _tiktok_profile_evidence(profile: dict[str, Any]) -> dict[str, Any]:
    return evidence_item(
        kind="tiktok_profile",
        value={
            "handle": profile.get("handle"),
            "profile_url": profile.get("profile_url"),
            "follower_count": profile.get("follower_count"),
            "specialty_key": profile.get("specialty_key"),
        },
        source=PROVENANCE_SOURCE,
        source_url=profile.get("profile_url"),
        confidence=1.0,
    )


def tiktok_creator_angle(
    profile: dict[str, Any], *, brief_exists: bool = False
) -> dict[str, Any]:
    videos = profile.get("top_videos") or []
    urls = [v.get("url") or v.get("video_url") for v in videos[:3] if isinstance(v, dict)]
    urls = [u for u in urls if u]
    return evidence_item(
        kind="tiktok_creator_angle",
        value={
            "handle": profile.get("handle"),
            "profile_url": profile.get("profile_url"),
            "follower_count": profile.get("follower_count"),
            "posts_30d": profile.get("posts_30d"),
            "growth_intent_level": profile.get("growth_intent_level"),
            "growth_intent_quote": profile.get("positioning_line"),
            "specialty_key": profile.get("specialty_key"),
            "positioning_line": profile.get("positioning_line"),
            "top_video_urls": urls,
            "customer_score": profile.get("customer_score"),
            "score_breakdown": profile.get("score_breakdown") or {},
            "l3_brief_exists": brief_exists,
        },
        source=PROVENANCE_SOURCE,
        source_url=profile.get("profile_url"),
    )


def _usable_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Promotion uses confirmed links only. name_only stays out unless confirmed."""
    usable = []
    for link in links:
        if link.get("status") != "confirmed":
            continue
        usable.append(link)
    return usable


def _confirmed_or_auto(links: list[dict[str, Any]], table: str) -> dict[str, Any] | None:
    for link in _usable_links(links):
        if link.get("target_table") == table:
            return link
    return None


def resolve_clinic_id(
    profile: dict[str, Any],
    links: list[dict[str, Any]],
    *,
    clinics_by_id: dict[str, dict[str, Any]],
    clinics_by_domain: dict[str, list[dict[str, Any]]],
    practitioners_by_id: dict[str, dict[str, Any]],
) -> tuple[str | None, str]:
    """Return (clinic_intelligence_id or None, how). None means insert a solo clinic."""
    intel_link = _confirmed_or_auto(links, "gtm_clinic_intelligence")
    if intel_link and intel_link.get("target_id") in clinics_by_id:
        return intel_link["target_id"], "confirmed_clinic_link"

    prac_link = _confirmed_or_auto(links, "integrated_practitioners")
    if prac_link:
        prac = practitioners_by_id.get(prac_link["target_id"]) or {}
        host = host_of(prac.get("website"))
        if host and clinics_by_domain.get(host):
            return clinics_by_domain[host][0]["id"], "practitioner_website_domain"

    existing = [
        c
        for c in clinics_by_id.values()
        if c.get("source_creator_profile_id") == profile["id"]
    ]
    if existing:
        return existing[0]["id"], "source_creator_profile_id"

    return None, "insert_solo"


def _clinic_payload(profile: dict[str, Any], *, existing_id: str | None) -> dict[str, Any]:
    provenance = make_provenance(
        source=PROVENANCE_SOURCE,
        lane=PROVENANCE_LANE,
        source_url=profile.get("profile_url"),
        extractor="gtm_pipeline.creators.promote",
    )
    specialty = profile.get("specialty_key")
    payload: dict[str, Any] = {
        "source_creator_profile_id": profile["id"],
        "evidence": [_tiktok_profile_evidence(profile)],
        "provenance": provenance,
    }
    if existing_id:
        payload["id"] = existing_id
        return payload
    payload.update(
        {
            "clinic_name": _clinic_name(profile),
            "website_url": _own_site_url(profile),
            "visible_clinic_size": "solo",
            "specialties": [specialty] if specialty else [],
            "email": _bio_email(profile),
        }
    )
    return payload


def _person_payload(
    profile: dict[str, Any], *, role: str, brief_exists: bool
) -> dict[str, Any]:
    score = profile.get("customer_score")
    try:
        priority = int(round(float(score))) if score is not None else 50
    except (TypeError, ValueError):
        priority = 50
    return {
        "full_name": _display_name(profile),
        "role": role,
        "specialty": profile.get("specialty_key"),
        "email": _bio_email(profile),
        "priority": max(0, min(priority, 100)),
        "social_profiles": _social_profiles(profile),
        "creator_profile_id": profile["id"],
        "evidence": [_tiktok_profile_evidence(profile), tiktok_creator_angle(profile, brief_exists=brief_exists)],
        "provenance": make_provenance(
            source=PROVENANCE_SOURCE,
            lane=PROVENANCE_LANE,
            source_url=profile.get("profile_url"),
            extractor="gtm_pipeline.creators.promote",
        ),
        "reasons": ["tiktok_creator"],
    }


def _fill_existing_person(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {"id": existing["id"]}
    social = dict(existing.get("social_profiles") or {})
    social.update(incoming.get("social_profiles") or {})
    patch["social_profiles"] = social
    if not existing.get("creator_profile_id"):
        patch["creator_profile_id"] = incoming.get("creator_profile_id")
    if not (existing.get("email") or "").strip() and incoming.get("email"):
        patch["email"] = incoming["email"]
    return patch


def eligible(profile: dict[str, Any]) -> bool:
    if profile.get("do_not_contact"):
        return False
    if profile.get("review_status") != "confirmed":
        return False
    if profile.get("lane") not in {"customer", "both"}:
        return False
    if profile.get("geo_country") != "GB":
        return False
    return True


def append_contact_evidence(
    clinic_intelligence_id: str,
    item: dict[str, Any],
    *,
    client: Any,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    rows = (
        client.table("gtm_outreach_contacts")
        .select("id, evidence")
        .eq("clinic_intelligence_id", clinic_intelligence_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return
    evidence = list(rows[0].get("evidence") or [])
    if any(isinstance(e, dict) and e.get("kind") == "tiktok_creator_angle" for e in evidence):
        evidence = [
            item if isinstance(e, dict) and e.get("kind") == "tiktok_creator_angle" else e
            for e in evidence
        ]
        if not any(isinstance(e, dict) and e.get("kind") == "tiktok_creator_angle" for e in evidence):
            evidence.append(item)
    else:
        evidence.append(item)
    client.table("gtm_outreach_contacts").update({"evidence": evidence}).eq(
        "id", rows[0]["id"]
    ).execute()


def _load_links(client: Any, profile_id: str) -> list[dict[str, Any]]:
    return (
        client.table("creator_links")
        .select("*")
        .eq("creator_profile_id", profile_id)
        .execute()
        .data
        or []
    )


def _lookup_person(
    client: Any,
    clinic_id: str,
    profile: dict[str, Any],
    links: list[dict[str, Any]],
) -> dict[str, Any] | None:
    people_link = _confirmed_or_auto(links, "gtm_clinic_people")
    if people_link:
        found = (
            client.table("gtm_clinic_people")
            .select("*")
            .eq("id", people_link["target_id"])
            .limit(1)
            .execute()
            .data
            or []
        )
        if found:
            return found[0]
    by_creator = (
        client.table("gtm_clinic_people")
        .select("*")
        .eq("clinic_intelligence_id", clinic_id)
        .eq("creator_profile_id", profile["id"])
        .limit(1)
        .execute()
        .data
        or []
    )
    if by_creator:
        return by_creator[0]
    name_key = person_name_key(profile.get("nickname") or profile.get("handle"))
    if not name_key:
        return None
    people = (
        client.table("gtm_clinic_people")
        .select("*")
        .eq("clinic_intelligence_id", clinic_id)
        .execute()
        .data
        or []
    )
    for person in people:
        if person_name_key(person.get("full_name")) == name_key:
            return person
    return None


def promote_one(
    profile: dict[str, Any],
    *,
    client: Any,
    dry_run: bool,
    clinics_by_id: dict[str, dict[str, Any]],
    clinics_by_domain: dict[str, list[dict[str, Any]]],
    practitioners_by_id: dict[str, dict[str, Any]],
    brief_handles: set[str],
    links: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not eligible(profile):
        return {"handle": profile.get("handle"), "skipped": True, "reason": "not_eligible"}

    links = links if links is not None else _load_links(client, profile["id"])
    clinic_id, how = resolve_clinic_id(
        profile,
        links,
        clinics_by_id=clinics_by_id,
        clinics_by_domain=clinics_by_domain,
        practitioners_by_id=practitioners_by_id,
    )
    created_clinic = clinic_id is None
    payload = _clinic_payload(profile, existing_id=clinic_id)
    intel = upsert_clinic_intelligence(payload, dry_run=dry_run)
    clinic_id = intel.get("id") or clinic_id or (None if dry_run else None)
    if dry_run and not clinic_id:
        clinic_id = f"dry-clinic:{profile['id']}"

    role = "founder" if created_clinic else "specialist"
    brief_exists = (profile.get("handle") or "") in brief_handles or profile.get("deep_status") in {
        "brief_draft",
        "brief_confirmed",
    }
    person_in = _person_payload(profile, role=role, brief_exists=brief_exists)
    existing_person = None if dry_run else _lookup_person(client, clinic_id, profile, links)
    if existing_person:
        patch = _fill_existing_person(existing_person, person_in)
        if not dry_run:
            client.table("gtm_clinic_people").update(patch).eq("id", existing_person["id"]).execute()
        person_id = existing_person["id"]
        people_n = 1
    else:
        people_n = upsert_clinic_people(clinic_id, [person_in], dry_run=dry_run)
        person_id = None
        if not dry_run and clinic_id:
            found = (
                client.table("gtm_clinic_people")
                .select("id")
                .eq("clinic_intelligence_id", clinic_id)
                .eq("creator_profile_id", profile["id"])
                .limit(1)
                .execute()
                .data
                or []
            )
            person_id = found[0]["id"] if found else None

    if not dry_run and clinic_id:
        client.table("creator_profiles").update(
            {
                "promoted_clinic_intelligence_id": clinic_id,
                "promoted_person_id": person_id,
                "promoted_at": make_provenance(source=PROVENANCE_SOURCE)["captured_at"],
            }
        ).eq("id", profile["id"]).execute()

    return {
        "handle": profile.get("handle"),
        "skipped": False,
        "clinic_intelligence_id": clinic_id,
        "person_id": person_id,
        "clinic_resolution": how,
        "created_clinic": created_clinic,
        "people_upserted": people_n,
        "dry_run": dry_run,
    }


def promote_creators(
    *,
    handle: str | None = None,
    all_confirmed: bool = False,
    dry_run: bool = False,
    client: Any | None = None,
    profiles: list[dict[str, Any]] | None = None,
    links_by_profile: dict[str, list[dict[str, Any]]] | None = None,
    refresh: bool = True,
) -> dict[str, Any]:
    """Idempotent promote. Does not insert clinic_accounts rows."""
    configured = supabase_configured()
    if client is None and profiles is None:
        if not configured:
            return {"dry_run": True, "promoted": 0, "reason": "supabase_not_configured"}
        client = get_client()
    persist = bool(client) and configured and not dry_run

    if profiles is None:
        rows = fetch_all(lambda: client.table("creator_profiles").select("*"), page=1000)
        if handle:
            want = handle.strip().lstrip("@").lower()
            rows = [r for r in rows if (r.get("handle") or "").lower() == want]
        profiles = [p for p in rows if eligible(p)]
        if handle and not profiles:
            return {"dry_run": not persist, "promoted": 0, "reason": "not_eligible_or_missing"}
    else:
        profiles = [p for p in profiles if eligible(p)]
        if handle:
            want = handle.strip().lstrip("@").lower()
            profiles = [p for p in profiles if (p.get("handle") or "").lower() == want]

    clinics = []
    practitioners = []
    briefs: set[str] = set()
    if client is not None:
        clinics = fetch_all(
            lambda: client.table("gtm_clinic_intelligence").select(
                "id, clinic_name, website_url, specialties, source_creator_profile_id, doctify_url"
            ),
            page=1000,
        )
        practitioners = fetch_all(
            lambda: client.table("integrated_practitioners").select("id, name, website"),
            page=1000,
        )
        brief_rows = fetch_all(
            lambda: client.table("creator_peer_briefs").select("account_handle, status"),
            page=1000,
        )
        briefs = {
            (r.get("account_handle") or "")
            for r in brief_rows
            if r.get("status") in {"draft", "confirmed"}
        }

    clinics_by_id = {c["id"]: c for c in clinics if c.get("id")}
    clinics_by_domain: dict[str, list[dict[str, Any]]] = {}
    for clinic in clinics:
        host = host_of(clinic.get("website_url"))
        if host:
            clinics_by_domain.setdefault(host, []).append(clinic)
    practitioners_by_id = {p["id"]: p for p in practitioners if p.get("id")}

    results = []
    for profile in profiles:
        links = (links_by_profile or {}).get(profile["id"])
        if links is None and client is not None:
            links = _load_links(client, profile["id"])
        results.append(
            promote_one(
                profile,
                client=client,
                dry_run=not persist,
                clinics_by_id=clinics_by_id,
                clinics_by_domain=clinics_by_domain,
                practitioners_by_id=practitioners_by_id,
                brief_handles=briefs,
                links=links or [],
            )
        )

    promoted_ids = [
        r["clinic_intelligence_id"]
        for r in results
        if not r.get("skipped") and r.get("clinic_intelligence_id")
    ]
    cohort = None
    outreach = None
    if persist and refresh and promoted_ids:
        cohort = refresh_cohort(COHORT, dry_run=False)
        outreach = refresh_outreach_contacts(
            cqc_named_only=False, cohort=COHORT, dry_run=False
        )
        for profile, result in zip(profiles, results):
            if result.get("skipped") or not result.get("clinic_intelligence_id"):
                continue
            append_contact_evidence(
                result["clinic_intelligence_id"],
                tiktok_creator_angle(
                    profile,
                    brief_exists=(profile.get("handle") or "") in briefs,
                ),
                client=client,
                dry_run=False,
            )

    return {
        "dry_run": not persist,
        "scanned": len(profiles),
        "promoted": sum(1 for r in results if not r.get("skipped")),
        "skipped": sum(1 for r in results if r.get("skipped")),
        "results": results,
        "cohort": cohort,
        "outreach": outreach,
        "all_confirmed": all_confirmed or handle is None,
    }
