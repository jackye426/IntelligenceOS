"""Owner discovery from integrated_practitioners.about (P0a-owners).

Scan practitioner bios for leadership keywords. If a clinic link exists,
attach evidence to gtm_clinic_*; otherwise upsert gtm_unmatched_owners
(never drop; keep email). Upsert key: practitioner_id.
"""

from __future__ import annotations

import logging
from typing import Any

from gtm_pipeline.scoring import scan_leadership
from gtm_pipeline.shared.provenance import evidence_item, make_provenance
from gtm_pipeline.shared.supabase_client import get_client, supabase_configured
from gtm_pipeline.sync.unmatched_owners import upsert_unmatched_owner

logger = logging.getLogger(__name__)

PAGE_SIZE = 500


def _fetch_practitioners_with_about(*, limit: int | None = None) -> list[dict[str, Any]]:
    client = get_client()
    rows: list[dict[str, Any]] = []
    offset = 0
    # Schema uses locations/website — there is no clinic_name / clinic_id column.
    select_cols = "id, name, email, emails, about, locations, website, specialty, title"
    while True:
        query = (
            client.table("integrated_practitioners")
            .select(select_cols)
            .not_.is_("about", "null")
            .range(offset, offset + PAGE_SIZE - 1)
        )
        batch = query.execute().data or []
        rows.extend(batch)
        if limit is not None and len(rows) >= limit:
            return rows[:limit]
        if len(batch) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def _best_email(row: dict[str, Any]) -> str:
    if row.get("email"):
        return str(row["email"])
    emails = row.get("emails") or []
    if isinstance(emails, list) and emails:
        first = emails[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            for k in ("email", "address", "value"):
                if first.get(k):
                    return str(first[k])
    return ""


def _clinic_name_candidates(row: dict[str, Any]) -> list[str]:
    """Best-effort clinic/org names from locations JSON (no clinic_name column)."""
    names: list[str] = []
    locations = row.get("locations")
    if isinstance(locations, list):
        for loc in locations:
            if isinstance(loc, str) and loc.strip():
                names.append(loc.strip())
            elif isinstance(loc, dict):
                for k in ("name", "clinic_name", "practice", "hospital", "label"):
                    v = loc.get(k)
                    if isinstance(v, str) and v.strip():
                        names.append(v.strip())
                        break
    elif isinstance(locations, dict):
        for k in ("name", "clinic_name"):
            v = locations.get(k)
            if isinstance(v, str) and v.strip():
                names.append(v.strip())
    # Dedupe preserving order
    return list(dict.fromkeys(names))


def _find_clinic_account_id(client, row: dict[str, Any]) -> str | None:
    for clinic_name in _clinic_name_candidates(row):
        hits = (
            client.table("clinic_accounts")
            .select("id, name")
            .ilike("name", f"%{clinic_name}%")
            .limit(5)
            .execute()
            .data
            or []
        )
        if len(hits) == 1:
            return hits[0]["id"]
        for h in hits:
            if (h.get("name") or "").lower() == clinic_name.lower():
                return h["id"]
    return None


def discover_owners(
    *,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Scan practitioners and upsert unmatched owners / attach clinic evidence."""
    if not supabase_configured() and not dry_run:
        raise RuntimeError(
            "Supabase credentials required (or pass --dry-run). "
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
        )

    counts = {
        "scanned": 0,
        "leadership_hits": 0,
        "matched_clinic": 0,
        "unmatched_upserted": 0,
        "skipped_no_about": 0,
    }

    if dry_run and not supabase_configured():
        logger.warning("dry-run without Supabase — nothing to scan")
        return counts

    client = get_client()
    rows = _fetch_practitioners_with_about(limit=limit)
    for row in rows:
        counts["scanned"] += 1
        about = (row.get("about") or "").strip()
        if not about:
            counts["skipped_no_about"] += 1
            continue

        hit = scan_leadership(about)
        if not hit:
            continue
        counts["leadership_hits"] += 1

        practitioner_id = str(row.get("id") or "")
        if not practitioner_id:
            continue

        email = _best_email(row)
        clinic_account_id = _find_clinic_account_id(client, row)
        evidence = [
            evidence_item(
                kind="leadership_about",
                value={
                    "role": hit.role,
                    "keywords": hit.keywords,
                    "snippets": hit.snippets,
                },
                source="integrated_practitioners",
                confidence=0.7,
            )
        ]
        provenance = make_provenance(
            source="integrated_practitioners",
            lane="owner_discovery",
            extractor="about_keyword_scan_v1",
            extra={"practitioner_id": practitioner_id},
        )

        payload = {
            "practitioner_id": practitioner_id,
            "full_name": row.get("name") or "",
            "email": email,
            "about": about,
            "leadership_role": hit.role,
            "leadership_keywords": hit.keywords,
            "source_table": "integrated_practitioners",
            "evidence": evidence,
            "provenance": provenance,
        }

        if clinic_account_id:
            counts["matched_clinic"] += 1
            # Still keep an unmatched row? Plan says: if matched → attach evidence;
            # if unmatched → upsert unmatched. Matched path attaches to clinic intel.
            if dry_run:
                logger.info(
                    "[dry-run] would attach owner %s to clinic %s",
                    practitioner_id,
                    clinic_account_id,
                )
                continue
            from gtm_pipeline.sync.clinic_intelligence import attach_owner_evidence

            attach_owner_evidence(
                clinic_account_id=clinic_account_id,
                person_name=payload["full_name"],
                role=hit.role,
                email=email,
                evidence=evidence,
                provenance=provenance,
                reasons=hit.keywords,
            )
        else:
            if dry_run:
                counts["unmatched_upserted"] += 1
                logger.info(
                    "[dry-run] would upsert unmatched owner %s (%s)",
                    payload["full_name"],
                    email,
                )
                continue
            upsert_unmatched_owner(payload)
            counts["unmatched_upserted"] += 1

    return counts
