"""Batch-enrich gtm_clinic_people from CQC RM/NI → practitioner email matches."""

from __future__ import annotations

import logging
from typing import Any

from gtm_pipeline.person_resolve import match_cqc_people_against_practitioners
from gtm_pipeline.shared.provenance import evidence_item, make_provenance, utc_now_iso
from gtm_pipeline.shared.supabase_client import get_client, supabase_configured

logger = logging.getLogger(__name__)


def enrich_cqc_people_from_practitioners(
    *,
    limit: int | None = None,
    min_confidence: float = 0.82,
    dry_run: bool = False,
    page_size: int = 200,
    clinic_intelligence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """For clinics with CQC RM/NI, match practitioners and attach emails."""
    stats: dict[str, Any] = {
        "clinics_scanned": 0,
        "cqc_people_named": 0,
        "matched_practitioner": 0,
        "with_email": 0,
        "people_rows_updated": 0,
        "intel_bumped": 0,
        "dry_run": dry_run,
        "errors": [],
    }

    if dry_run or not supabase_configured():
        stats["dry_run"] = True
        return stats

    client = get_client()
    offset = 0
    processed = 0
    id_filter = [x for x in (clinic_intelligence_ids or []) if x]

    while True:
        if limit is not None and processed >= limit:
            break
        q = (
            client.table("gtm_clinic_intelligence")
            .select(
                "id, clinic_account_id, clinic_name, founder_score, structure, evidence, "
                "cqc_registered_manager, cqc_nominated_individual"
            )
            .not_.is_("cqc_location_id", "null")
            .order("updated_at", desc=True)
        )
        if id_filter:
            # Process filter set in chunks via .in_
            chunk = id_filter[offset : offset + page_size]
            if not chunk:
                break
            q = q.in_("id", chunk)
            rows = q.execute().data or []
            offset += page_size
        else:
            q = q.range(offset, offset + page_size - 1)
            rows = q.execute().data or []
            if not rows:
                break
            offset += page_size

        if not rows and id_filter:
            break

        for intel in rows:
            if limit is not None and processed >= limit:
                break
            processed += 1
            stats["clinics_scanned"] += 1
            ni = (intel.get("cqc_nominated_individual") or "").strip()
            rm = (intel.get("cqc_registered_manager") or "").strip()
            if ni:
                stats["cqc_people_named"] += 1
            if rm and rm != ni:
                stats["cqc_people_named"] += 1

            try:
                # Pull near-misses for review; auto-apply only at min_confidence
                result = match_cqc_people_against_practitioners(
                    nominated_individual=ni,
                    registered_manager=rm,
                    min_confidence=0.50,
                    dry_run=False,
                )
            except Exception as exc:  # noqa: BLE001
                stats["errors"].append({"clinic": intel.get("clinic_name"), "error": str(exc)})
                continue

            matched_any = False
            email_any = False
            from gtm_pipeline import config as gtm_config
            from gtm_pipeline.sync.match_reviews import maybe_queue_match_review

            for m in result.get("matches") or []:
                conf = float(m.get("confidence") or 0)
                if not m.get("practitioner_id"):
                    continue
                if conf < min_confidence:
                    if conf >= gtm_config.MATCH_REVIEW_THRESHOLD:
                        maybe_queue_match_review(
                            entity_type="person_clinic",
                            candidate={
                                "practitioner_id": m.get("practitioner_id"),
                                "matched_name": m.get("matched_name"),
                                "email": m.get("email"),
                                "role": m.get("role"),
                            },
                            target={
                                "query_name": m.get("query_name"),
                                "clinic_name": intel.get("clinic_name"),
                                "role": m.get("role"),
                            },
                            confidence=conf,
                            reasons=list(m.get("reasons") or []),
                            clinic_intelligence_id=intel["id"],
                            clinic_account_id=intel.get("clinic_account_id"),
                            dedupe_key=(
                                f"person_clinic:{intel['id']}:{m.get('role')}:"
                                f"{m.get('practitioner_id')}"
                            ),
                            dry_run=False,
                        )
                        stats.setdefault("review_queued", 0)
                        stats["review_queued"] += 1
                    continue
                stats["matched_practitioner"] += 1
                matched_any = True
                email = (m.get("email") or "").strip()
                if email:
                    stats["with_email"] += 1
                    email_any = True

                # Update existing CQC role people row, or insert
                people = (
                    client.table("gtm_clinic_people")
                    .select("id, email, reasons, evidence")
                    .eq("clinic_intelligence_id", intel["id"])
                    .eq("role", m["role"])
                    .limit(5)
                    .execute()
                    .data
                    or []
                )
                # Prefer name match within role
                target = None
                for p in people:
                    target = p
                    break
                payload = {
                    "full_name": m.get("matched_name") or m.get("query_name"),
                    "role": m["role"],
                    "email": email or None,
                    "priority": 95 if email else 88,
                    "reasons": [
                        {
                            "source": "practitioner_match",
                            "practitioner_id": m.get("practitioner_id"),
                            "confidence": m.get("confidence"),
                            "query_name": m.get("query_name"),
                        }
                    ],
                    "evidence": [
                        evidence_item(
                            kind="cqc_practitioner_match",
                            value=m,
                            source="integrated_practitioners",
                            confidence=m.get("confidence"),
                        )
                    ],
                    "provenance": make_provenance(
                        source="people_enrich_cqc", lane="person_resolve"
                    ),
                    "updated_at": utc_now_iso(),
                    "clinic_intelligence_id": intel["id"],
                    "clinic_account_id": intel.get("clinic_account_id"),
                }
                if target:
                    client.table("gtm_clinic_people").update(payload).eq(
                        "id", target["id"]
                    ).execute()
                else:
                    client.table("gtm_clinic_people").insert(payload).execute()
                stats["people_rows_updated"] += 1

            if matched_any:
                # Bump founder score modestly when we have a practitioner (esp. email)
                bump = 12 if email_any else 6
                new_score = min(100, int(intel.get("founder_score") or 20) + bump)
                evidence = list(intel.get("evidence") or [])
                evidence.append(
                    evidence_item(
                        kind="practitioner_email_enrichment",
                        value={"matched": True, "with_email": email_any, "bump": bump},
                        source="people_enrich_cqc",
                    )
                )
                client.table("gtm_clinic_intelligence").update(
                    {
                        "founder_score": new_score,
                        "structure": intel.get("structure") or "cqc_decision_maker",
                        "evidence": evidence,
                        "updated_at": utc_now_iso(),
                    }
                ).eq("id", intel["id"]).execute()
                stats["intel_bumped"] += 1

        if id_filter:
            if offset >= len(id_filter):
                break
        elif len(rows) < page_size:
            break

    return stats
