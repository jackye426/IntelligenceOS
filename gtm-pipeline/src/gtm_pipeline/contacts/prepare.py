"""Contact prepare: CQC rematch-only + people enrich for cohort members."""

from __future__ import annotations

import logging
from typing import Any

from gtm_pipeline import config
from gtm_pipeline.cqc_directory import match_directory
from gtm_pipeline.cqc_location import fetch_location
from gtm_pipeline.segments import get_cohort, list_members, refresh_cohort
from gtm_pipeline.shared.supabase_client import get_client, supabase_configured
from gtm_pipeline.sync.clinic_intelligence import upsert_clinic_intelligence
from gtm_pipeline.sync.enrich_cqc_people import enrich_cqc_people_from_practitioners
from gtm_pipeline.sync.match_reviews import maybe_queue_match_review

logger = logging.getLogger(__name__)


def rematch_cqc_for_clinic(
    intel: dict[str, Any],
    *,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Directory match + optional location scrape; queue ambiguous band."""
    if intel.get("cqc_location_id") and not force:
        return {"skipped": True, "reason": "already_has_cqc"}

    hits = match_directory(
        name=intel.get("clinic_name") or "",
        postcode=intel.get("postcode") or "",
        address=intel.get("address") or "",
        website=intel.get("website_url") or "",
        phone=intel.get("phone") or "",
        top_k=3,
    )
    if not hits:
        return {"matched": False, "review_queued": False}

    best = hits[0]
    if best.confidence < config.MATCH_REVIEW_THRESHOLD:
        return {
            "matched": False,
            "best": best.as_dict(),
            "reason": "below_review_threshold",
        }

    if best.confidence < config.MATCH_AUTO_ACCEPT:
        review = maybe_queue_match_review(
            entity_type="clinic_cqc",
            candidate=best.as_dict(),
            target={
                "clinic_name": intel.get("clinic_name"),
                "doctify_url": intel.get("doctify_url"),
                "postcode": intel.get("postcode"),
                "website_url": intel.get("website_url"),
            },
            confidence=best.confidence,
            reasons=list(best.reasons or []),
            clinic_intelligence_id=intel.get("id"),
            clinic_account_id=intel.get("clinic_account_id"),
            dedupe_key=f"clinic_cqc:{intel.get('id')}:{best.location_id or best.name}",
            dry_run=dry_run,
        )
        return {
            "matched": False,
            "review_queued": review is not None,
            "best": best.as_dict(),
            "reason": "ambiguous_queued_for_review",
        }

    overview = None
    url = best.location_url or (
        f"https://www.cqc.org.uk/location/{best.location_id}" if best.location_id else ""
    )
    if url and not dry_run:
        try:
            overview = fetch_location(url)
        except Exception as exc:
            logger.warning("CQC location scrape failed %s: %s", url, exc)

    payload: dict[str, Any] = {
        "doctify_url": intel.get("doctify_url"),
        "clinic_name": intel.get("clinic_name"),
        "cqc_location_id": best.location_id
        or (overview.location_id if overview else None),
        "cqc_location_url": (overview.location_url if overview else None) or best.location_url,
        "cqc_provider_name": (overview.provider_name if overview else None)
        or best.provider_name
        or None,
        "cqc_match_confidence": best.confidence,
        "cqc_match_reasons": list(best.reasons or []),
    }
    if overview:
        payload.update(
            {
                "cqc_registered_since": overview.registered_since.isoformat()
                if overview.registered_since
                else None,
                "cqc_specialisms": overview.specialisms,
                "cqc_registered_manager": overview.registered_manager or None,
                "cqc_nominated_individual": overview.nominated_individual or None,
            }
        )
    sync = upsert_clinic_intelligence(payload, dry_run=dry_run)
    return {
        "matched": True,
        "scraped": overview is not None,
        "best": best.as_dict(),
        "sync": {"id": sync.get("id")} if isinstance(sync, dict) else sync,
    }


def prepare_cohort_contacts(
    slug: str,
    *,
    limit: int | None = 50,
    dry_run: bool = False,
    skip_cqc: bool = False,
    skip_people: bool = False,
    force_cqc: bool = False,
) -> dict[str, Any]:
    """Rematch CQC + enrich people for needs_contact members; refresh cohort."""
    if not supabase_configured():
        raise RuntimeError("Supabase not configured")

    cohort = get_cohort(slug)
    if not cohort:
        raise ValueError(f"Unknown cohort: {slug}")

    # Ensure membership exists
    refresh_cohort(slug, dry_run=False)
    members = list_members(slug, status="needs_contact", limit=limit or 500)["members"]
    if limit is not None:
        members = members[:limit]

    client = get_client()
    stats: dict[str, Any] = {
        "slug": slug,
        "members": len(members),
        "cqc_matched": 0,
        "cqc_review_queued": 0,
        "cqc_skipped": 0,
        "people_enrich": None,
        "dry_run": dry_run,
        "errors": [],
    }

    if not skip_cqc:
        for m in members:
            cid = m["clinic_intelligence_id"]
            rows = (
                client.table("gtm_clinic_intelligence")
                .select(
                    "id, clinic_account_id, clinic_name, doctify_url, postcode, address, "
                    "website_url, phone, cqc_location_id"
                )
                .eq("id", cid)
                .limit(1)
                .execute()
                .data
                or []
            )
            if not rows:
                continue
            try:
                out = rematch_cqc_for_clinic(rows[0], dry_run=dry_run, force=force_cqc)
                if out.get("skipped"):
                    stats["cqc_skipped"] += 1
                elif out.get("matched"):
                    stats["cqc_matched"] += 1
                elif out.get("review_queued"):
                    stats["cqc_review_queued"] += 1
            except Exception as exc:
                logger.exception("cqc rematch failed for %s", cid)
                stats["errors"].append({"clinic_intelligence_id": cid, "error": str(exc)})

    if not skip_people and not dry_run:
        clinic_ids = [m["clinic_intelligence_id"] for m in members if m.get("clinic_intelligence_id")]
        stats["people_enrich"] = enrich_cqc_people_from_practitioners(
            limit=None,
            min_confidence=0.82,
            dry_run=False,
            clinic_intelligence_ids=clinic_ids or None,
        )

    refreshed = refresh_cohort(slug, dry_run=False)
    stats["after_refresh"] = refreshed.get("status_counts")
    return stats
