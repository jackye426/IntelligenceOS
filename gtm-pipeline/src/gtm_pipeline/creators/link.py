"""Match GB creator profiles onto existing identity indexes. No clinic_accounts writes."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import urlparse

from gtm_pipeline.creators.paging import fetch_all
from gtm_pipeline.segments.specialty import specialty_to_keys
from gtm_pipeline.shared.name import person_name_key
from gtm_pipeline.shared.supabase_client import get_client, supabase_configured
from gtm_pipeline.sync.match_reviews import maybe_queue_match_review

logger = logging.getLogger(__name__)

LINK_METHODS: dict[str, tuple[float, str]] = {
    "gmc_in_bio": (0.99, "confirmed"),
    "email_exact": (0.95, "confirmed"),
    "bio_domain": (0.90, "suggested"),
    "name_specialty": (0.75, "suggested"),
    "name_only": (0.50, "suggested"),
}

# Promotion may use these without a human confirm. name_only is never auto-used.
AUTO_PROMOTABLE_METHODS = frozenset({"gmc_in_bio", "email_exact"})

DEFAULT_LANES = ("customer", "both")
PAGE = 1000


@dataclass
class LinkHit:
    target_table: str
    target_id: str
    method: str
    confidence: float
    status: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class IdentityIndexes:
    practitioners_by_gmc: dict[str, list[dict[str, Any]]]
    practitioners_by_email: dict[str, list[dict[str, Any]]]
    practitioners_by_name: dict[str, list[dict[str, Any]]]
    practitioners_by_domain: dict[str, list[dict[str, Any]]]
    people_by_email: dict[str, list[dict[str, Any]]]
    people_by_name: dict[str, list[dict[str, Any]]]
    clinics_by_domain: dict[str, list[dict[str, Any]]]
    outreach_by_practitioner: dict[str, dict[str, Any]]
    clinics: list[dict[str, Any]]


def host_of(url: str | None) -> str:
    if not url:
        return ""
    raw = url.strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    except ValueError:
        return ""
    return parsed.netloc.lower().removeprefix("www.")


def collect_emails(row: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for key in ("email", "canonical_email"):
        value = (row.get(key) or "").strip().lower()
        if value:
            out.add(value)
    emails = row.get("emails") or []
    if isinstance(emails, list):
        for item in emails:
            if isinstance(item, str) and item.strip():
                out.add(item.strip().lower())
            elif isinstance(item, dict):
                for k in ("email", "address", "value"):
                    if item.get(k):
                        out.add(str(item[k]).strip().lower())
    return {e for e in out if "@" in e}


def own_site_hosts(profile: dict[str, Any]) -> list[str]:
    hosts: list[str] = []
    for item in profile.get("bio_links") or []:
        if not isinstance(item, dict):
            continue
        if item.get("class") != "own_site":
            continue
        host = host_of(item.get("url"))
        if host:
            hosts.append(host)
    return list(dict.fromkeys(hosts))


def _practitioner_specialties(row: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for raw in (row.get("specialty"),):
        if raw:
            keys.update(specialty_to_keys(str(raw)))
    specs = row.get("specialties")
    if isinstance(specs, list):
        for item in specs:
            keys.update(specialty_to_keys(str(item)))
    elif isinstance(specs, str) and specs:
        keys.update(specialty_to_keys(specs))
    return keys


def build_indexes(
    *,
    practitioners: Iterable[dict[str, Any]],
    people: Iterable[dict[str, Any]],
    clinics: Iterable[dict[str, Any]],
    outreach: Iterable[dict[str, Any]],
) -> IdentityIndexes:
    by_gmc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    prac_email: dict[str, list[dict[str, Any]]] = defaultdict(list)
    prac_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    prac_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in practitioners:
        gmc = str(row.get("gmc_number") or "").strip()
        if gmc:
            by_gmc[gmc].append(row)
        for email in collect_emails(row):
            prac_email[email].append(row)
        name_key = person_name_key(row.get("name"))
        if name_key:
            prac_name[name_key].append(row)
        host = host_of(row.get("website"))
        if host:
            prac_domain[host].append(row)

    people_email: dict[str, list[dict[str, Any]]] = defaultdict(list)
    people_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in people:
        for email in collect_emails(row):
            people_email[email].append(row)
        name_key = person_name_key(row.get("full_name") or row.get("name"))
        if name_key:
            people_name[name_key].append(row)

    clinic_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    clinic_rows = list(clinics)
    for row in clinic_rows:
        host = host_of(row.get("website_url") or row.get("website"))
        if host:
            clinic_domain[host].append(row)

    outreach_by: dict[str, dict[str, Any]] = {}
    for row in outreach:
        pid = str(row.get("practitioner_id") or "")
        if pid:
            outreach_by[pid] = row

    return IdentityIndexes(
        practitioners_by_gmc=dict(by_gmc),
        practitioners_by_email=dict(prac_email),
        practitioners_by_name=dict(prac_name),
        practitioners_by_domain=dict(prac_domain),
        people_by_email=dict(people_email),
        people_by_name=dict(people_name),
        clinics_by_domain=dict(clinic_domain),
        outreach_by_practitioner=outreach_by,
        clinics=clinic_rows,
    )


def _hits_for_rows(
    rows: list[dict[str, Any]],
    *,
    table: str,
    id_field: str,
    method: str,
    extra: dict[str, Any],
) -> list[LinkHit]:
    confidence, status = LINK_METHODS[method]
    hits: list[LinkHit] = []
    seen: set[str] = set()
    for row in rows:
        target_id = str(row.get(id_field) or "")
        if not target_id or target_id in seen:
            continue
        seen.add(target_id)
        hits.append(
            LinkHit(
                target_table=table,
                target_id=target_id,
                method=method,
                confidence=confidence,
                status=status,
                evidence={**extra, "matched_name": row.get("name") or row.get("full_name") or row.get("clinic_name")},
            )
        )
    return hits


def match_profile(profile: dict[str, Any], indexes: IdentityIndexes) -> list[LinkHit]:
    """Return identity hits for one GB creator. Ambiguous top-confidence → suggested."""
    hits: list[LinkHit] = []

    gmc = str(profile.get("gmc_number_in_bio") or "").strip()
    if gmc:
        hits.extend(
            _hits_for_rows(
                indexes.practitioners_by_gmc.get(gmc) or [],
                table="integrated_practitioners",
                id_field="id",
                method="gmc_in_bio",
                extra={"gmc": gmc},
            )
        )

    emails = [e.lower() for e in (profile.get("bio_emails") or []) if e]
    for email in emails:
        hits.extend(
            _hits_for_rows(
                indexes.practitioners_by_email.get(email) or [],
                table="integrated_practitioners",
                id_field="id",
                method="email_exact",
                extra={"email": email},
            )
        )
        hits.extend(
            _hits_for_rows(
                indexes.people_by_email.get(email) or [],
                table="gtm_clinic_people",
                id_field="id",
                method="email_exact",
                extra={"email": email},
            )
        )

    for host in own_site_hosts(profile):
        hits.extend(
            _hits_for_rows(
                indexes.clinics_by_domain.get(host) or [],
                table="gtm_clinic_intelligence",
                id_field="id",
                method="bio_domain",
                extra={"domain": host},
            )
        )
        hits.extend(
            _hits_for_rows(
                indexes.practitioners_by_domain.get(host) or [],
                table="integrated_practitioners",
                id_field="id",
                method="bio_domain",
                extra={"domain": host},
            )
        )

    name_key = person_name_key(profile.get("nickname") or profile.get("handle"))
    specialty = (profile.get("specialty_key") or "").strip()
    if name_key:
        named = indexes.practitioners_by_name.get(name_key) or []
        people_named = indexes.people_by_name.get(name_key) or []
        if specialty:
            spec_prac = [r for r in named if specialty in _practitioner_specialties(r)]
            spec_people = [
                r
                for r in people_named
                if specialty in specialty_to_keys(str(r.get("specialty") or ""))
                or specialty == (r.get("specialty") or "")
            ]
            hits.extend(
                _hits_for_rows(
                    spec_prac,
                    table="integrated_practitioners",
                    id_field="id",
                    method="name_specialty",
                    extra={"name_key": name_key, "specialty_key": specialty},
                )
            )
            hits.extend(
                _hits_for_rows(
                    spec_people,
                    table="gtm_clinic_people",
                    id_field="id",
                    method="name_specialty",
                    extra={"name_key": name_key, "specialty_key": specialty},
                )
            )
            named_ids = {str(r.get("id")) for r in spec_prac}
            people_ids = {str(r.get("id")) for r in spec_people}
            leftover_prac = [r for r in named if str(r.get("id")) not in named_ids]
            leftover_people = [r for r in people_named if str(r.get("id")) not in people_ids]
        else:
            leftover_prac = named
            leftover_people = people_named
        hits.extend(
            _hits_for_rows(
                leftover_prac,
                table="integrated_practitioners",
                id_field="id",
                method="name_only",
                extra={"name_key": name_key},
            )
        )
        hits.extend(
            _hits_for_rows(
                leftover_people,
                table="gtm_clinic_people",
                id_field="id",
                method="name_only",
                extra={"name_key": name_key},
            )
        )

    # Dedup same (table, id, method); keep highest confidence.
    best: dict[tuple[str, str, str], LinkHit] = {}
    for hit in hits:
        key = (hit.target_table, hit.target_id, hit.method)
        prev = best.get(key)
        if prev is None or hit.confidence > prev.confidence:
            best[key] = hit
    # One method per target — GMC wins over name_only on the same practitioner.
    by_target: dict[tuple[str, str], LinkHit] = {}
    for hit in best.values():
        key = (hit.target_table, hit.target_id)
        prev = by_target.get(key)
        if prev is None or hit.confidence > prev.confidence:
            by_target[key] = hit
    unique = list(by_target.values())

    if unique:
        top = max(h.confidence for h in unique)
        top_hits = [h for h in unique if h.confidence == top]
        if len(top_hits) > 1:
            for hit in unique:
                if hit.confidence == top:
                    hit.status = "suggested"

    return unique


def _dnc_and_converted(
    hits: list[LinkHit], indexes: IdentityIndexes
) -> tuple[bool, bool]:
    dnc = False
    converted = False
    extra: list[LinkHit] = []
    for hit in hits:
        if hit.target_table != "integrated_practitioners":
            continue
        outreach = indexes.outreach_by_practitioner.get(hit.target_id)
        if not outreach:
            continue
        status = (outreach.get("status") or "").lower()
        if status == "dnc":
            dnc = True
        if status == "converted":
            converted = True
        extra.append(
            LinkHit(
                target_table="doctor_outreach",
                target_id=hit.target_id,
                method=hit.method,
                confidence=hit.confidence,
                status=hit.status,
                evidence={"outreach_status": status},
            )
        )
    hits.extend(extra)
    return dnc, converted


def load_indexes(*, client: Any | None = None) -> IdentityIndexes:
    client = client or get_client()
    practitioners = fetch_all(
        lambda: client.table("integrated_practitioners").select(
            "id, name, email, emails, website, specialty, specialties, gmc_number"
        ),
        page=PAGE,
    )
    people = fetch_all(
        lambda: client.table("gtm_clinic_people").select(
            "id, clinic_intelligence_id, full_name, email, specialty, creator_profile_id"
        ),
        page=PAGE,
    )
    clinics = fetch_all(
        lambda: client.table("gtm_clinic_intelligence").select(
            "id, clinic_name, website_url, specialties, source_creator_profile_id, doctify_url"
        ),
        page=PAGE,
    )
    outreach = fetch_all(
        lambda: client.table("doctor_outreach").select(
            "practitioner_id, status, canonical_email, normalized_name"
        ),
        page=PAGE,
    )
    return build_indexes(
        practitioners=practitioners,
        people=people,
        clinics=clinics,
        outreach=outreach,
    )


def load_profiles(
    *,
    lanes: tuple[str, ...] = DEFAULT_LANES,
    client: Any | None = None,
) -> list[dict[str, Any]]:
    client = client or get_client()
    rows = fetch_all(
        lambda: client.table("creator_profiles").select("*"),
        page=PAGE,
    )
    wanted = set(lanes)
    return [
        row
        for row in rows
        if row.get("geo_country") == "GB" and (not wanted or row.get("lane") in wanted)
    ]


def persist_links(
    profile: dict[str, Any],
    hits: list[LinkHit],
    *,
    dnc: bool,
    converted: bool,
    client: Any,
    dry_run: bool,
) -> list[dict[str, Any]]:
    rows = [
        {
            "creator_profile_id": profile["id"],
            "target_table": hit.target_table,
            "target_id": hit.target_id,
            "method": hit.method,
            "confidence": hit.confidence,
            "status": hit.status,
            "evidence": hit.evidence,
        }
        for hit in hits
    ]
    patch: dict[str, Any] = {}
    if dnc:
        patch["do_not_contact"] = True
    if converted:
        reasons = list(profile.get("lane_reasons") or [])
        if "doctor_outreach_converted" not in reasons:
            reasons.append("doctor_outreach_converted")
        patch["lane_reasons"] = reasons
    if patch:
        profile.update(patch)
    if dry_run:
        return rows
    for row in rows:
        client.table("creator_links").upsert(
            row, on_conflict="creator_profile_id,target_table,target_id"
        ).execute()
    if patch:
        client.table("creator_profiles").update(patch).eq("id", profile["id"]).execute()
    return rows


def recheck_duplicate_clinics(
    *,
    indexes: IdentityIndexes,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Flag creator-sourced clinics whose domain matches a Doctify clinic. Never auto-merge."""
    queued: list[dict[str, Any]] = []
    doctify_by_host: dict[str, list[dict[str, Any]]] = defaultdict(list)
    creator_clinics: list[dict[str, Any]] = []
    for clinic in indexes.clinics:
        host = host_of(clinic.get("website_url"))
        if not host:
            continue
        if clinic.get("source_creator_profile_id") and not clinic.get("doctify_url"):
            creator_clinics.append(clinic)
        elif clinic.get("doctify_url"):
            doctify_by_host[host].append(clinic)
    for clinic in creator_clinics:
        host = host_of(clinic.get("website_url"))
        targets = doctify_by_host.get(host) or []
        if not targets:
            continue
        creator_id = clinic.get("source_creator_profile_id")
        review = maybe_queue_match_review(
            entity_type="creator_clinic",
            candidate={
                "clinic_intelligence_id": clinic.get("id"),
                "clinic_name": clinic.get("clinic_name"),
                "website_url": clinic.get("website_url"),
                "source_creator_profile_id": creator_id,
            },
            target={
                "clinic_intelligence_id": targets[0].get("id"),
                "clinic_name": targets[0].get("clinic_name"),
                "website_url": targets[0].get("website_url"),
                "doctify_url": targets[0].get("doctify_url"),
            },
            confidence=0.90,
            reasons=["bio_domain_overlap", f"host={host}"],
            clinic_intelligence_id=targets[0].get("id"),
            dedupe_key=f"creator_clinic:{creator_id}",
            dry_run=dry_run,
            force_review=True,
        )
        if review:
            queued.append(review)
    return queued


def link_creators(
    *,
    lanes: tuple[str, ...] | list[str] = DEFAULT_LANES,
    dry_run: bool = False,
    recheck: bool = False,
    profiles: list[dict[str, Any]] | None = None,
    indexes: IdentityIndexes | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """GB customer/both creators → creator_links. Writes via GTM supabase, not marketing store."""
    lane_tuple = tuple(lanes) if not isinstance(lanes, tuple) else lanes
    configured = supabase_configured()
    if client is None and indexes is None and profiles is None:
        if not configured:
            return {"dry_run": True, "linked": 0, "reason": "supabase_not_configured"}
        client = get_client()
    if indexes is None:
        indexes = load_indexes(client=client)
    if profiles is None:
        profiles = load_profiles(lanes=lane_tuple, client=client)

    persist = client is not None and not dry_run and configured
    write_client = client
    linked = 0
    dnc_n = 0
    rows_out: list[dict[str, Any]] = []
    for profile in profiles:
        hits = match_profile(profile, indexes)
        dnc, converted = _dnc_and_converted(hits, indexes)
        if dnc:
            dnc_n += 1
        written = persist_links(
            profile,
            hits,
            dnc=dnc,
            converted=converted,
            client=write_client,
            dry_run=not persist,
        )
        if hits:
            linked += 1
        rows_out.append(
            {
                "handle": profile.get("handle"),
                "creator_profile_id": profile.get("id"),
                "hits": len(hits),
                "do_not_contact": dnc,
                "links": written,
            }
        )

    reviews: list[dict[str, Any]] = []
    if recheck:
        reviews = recheck_duplicate_clinics(indexes=indexes, dry_run=not persist)

    return {
        "dry_run": not persist,
        "scanned": len(profiles),
        "linked": linked,
        "do_not_contact": dnc_n,
        "recheck_reviews": len(reviews),
        "profiles": rows_out,
    }
