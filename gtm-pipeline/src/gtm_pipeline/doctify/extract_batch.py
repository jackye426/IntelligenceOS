"""Batch Doctify practice extract + optional gtm CQC enrich (no OG scraper)."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gtm_pipeline.doctify.extract import extract_practice_sync
from gtm_pipeline.shared.supabase_client import get_client, supabase_configured
from gtm_pipeline.sync.clinic_intelligence import sync_doctify_extract, upsert_clinic_intelligence

logger = logging.getLogger(__name__)

_CQC_MIN_CONFIDENCE = 0.80


@dataclass
class BatchItem:
    doctify_url: str
    clinic_name: str = ""
    clinic_intelligence_id: str | None = None
    founder_score: int = 0
    has_cqc: bool = False
    has_email_person: bool = False
    priority: int = 0


@dataclass
class BatchResult:
    attempted: int = 0
    extracted: int = 0
    upserted: int = 0
    cqc_matched: int = 0
    cqc_scraped: int = 0
    cqc_review_queued: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "extracted": self.extracted,
            "upserted": self.upserted,
            "cqc_matched": self.cqc_matched,
            "cqc_scraped": self.cqc_scraped,
            "cqc_review_queued": self.cqc_review_queued,
            "errors": self.errors,
            "items": self.items,
        }


def _priority(item: BatchItem) -> int:
    score = 0
    if item.has_email_person:
        score += 100
    if item.has_cqc:
        score += 50
    if item.founder_score >= 40:
        score += 20
    return score + min(item.founder_score, 19)


def load_urls_from_csv(path: Path | str) -> list[BatchItem]:
    items: list[BatchItem] = []
    with Path(path).open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = (
                row.get("doctify_url")
                or row.get("doctify_profile_url")
                or row.get("url")
                or ""
            ).strip()
            if not url:
                continue
            items.append(
                BatchItem(
                    doctify_url=url.rstrip("/"),
                    clinic_name=(row.get("clinic_name") or row.get("name") or "").strip(),
                )
            )
    return items


def load_urls_from_supabase(
    *,
    priority: bool = True,
    limit: int | None = None,
    only_pending_og: bool = False,
) -> list[BatchItem]:
    """Load practice URLs from gtm_clinic_intelligence."""
    if not supabase_configured():
        raise RuntimeError("Supabase not configured — cannot --from-supabase")

    client = get_client()
    rows: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while True:
        q = (
            client.table("gtm_clinic_intelligence")
            .select(
                "id, doctify_url, clinic_name, founder_score, cqc_location_id, provenance"
            )
            .not_.is_("doctify_url", "null")
            .neq("doctify_url", "")
            .range(offset, offset + page_size - 1)
        )
        batch = q.execute().data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    email_ids: set[str] = set()
    people_offset = 0
    while True:
        people = (
            client.table("gtm_clinic_people")
            .select("clinic_intelligence_id, email")
            .not_.is_("email", "null")
            .neq("email", "")
            .range(people_offset, people_offset + page_size - 1)
            .execute()
            .data
            or []
        )
        for p in people:
            cid = p.get("clinic_intelligence_id")
            if cid:
                email_ids.add(cid)
        if len(people) < page_size:
            break
        people_offset += page_size

    items: list[BatchItem] = []
    for row in rows:
        url = (row.get("doctify_url") or "").strip().rstrip("/")
        if not url:
            continue
        prov = row.get("provenance") or {}
        if only_pending_og:
            src = (prov.get("source") or "") if isinstance(prov, dict) else ""
            if src == "doctify" and (prov.get("extractor") or "") == "playwright_practice_v1":
                continue
            if not prov.get("og_pending_reextract") and src not in (
                "clinic_sales_scoped_csv",
                "",
            ):
                # Still allow OG-sourced rows without the flag
                if src and src != "clinic_sales_scoped_csv":
                    continue

        item = BatchItem(
            doctify_url=url,
            clinic_name=(row.get("clinic_name") or "").strip(),
            clinic_intelligence_id=row.get("id"),
            founder_score=int(row.get("founder_score") or 0),
            has_cqc=bool(row.get("cqc_location_id")),
            has_email_person=row.get("id") in email_ids,
        )
        item.priority = _priority(item)
        items.append(item)

    if priority:
        items.sort(key=lambda x: (x.priority, x.founder_score), reverse=True)
    if limit is not None:
        items = items[:limit]
    return items


def _apply_cqc(
    *,
    extract: Any,
    clinic_intelligence_id: str | None,
    clinic_account_id: str | None = None,
    dry_run: bool,
    min_confidence: float = _CQC_MIN_CONFIDENCE,
) -> dict[str, Any]:
    """Match directory + scrape location Overview; upsert CQC fields via gtm only.

    Confidence in [MATCH_REVIEW_THRESHOLD, MATCH_AUTO_ACCEPT) is flagged into
    ``gtm_match_reviews`` and not auto-applied.
    """
    from gtm_pipeline import config
    from gtm_pipeline.cqc_directory import match_directory
    from gtm_pipeline.cqc_location import fetch_location
    from gtm_pipeline.sync.match_reviews import maybe_queue_match_review

    hits = match_directory(
        name=extract.clinic_name or "",
        postcode=extract.postcode or "",
        address=extract.address or "",
        website=extract.website_url or "",
        phone=extract.phone or "",
        top_k=3,
    )
    if not hits:
        return {"matched": False, "best": None, "scraped": False, "review_queued": False}

    best = hits[0]
    if best.confidence < config.MATCH_REVIEW_THRESHOLD:
        return {
            "matched": False,
            "best": best.as_dict(),
            "scraped": False,
            "review_queued": False,
            "reason": "below_review_threshold",
        }

    if best.confidence < min_confidence:
        review = maybe_queue_match_review(
            entity_type="clinic_cqc",
            candidate=best.as_dict(),
            target={
                "clinic_name": extract.clinic_name,
                "doctify_url": extract.doctify_url,
                "postcode": extract.postcode,
                "website_url": extract.website_url,
                "address": extract.address,
            },
            confidence=best.confidence,
            reasons=list(best.reasons or []),
            provenance={
                "source": "doctify",
                "extractor": "playwright_practice_v1",
                "lane": "cqc_directory_match",
            },
            clinic_intelligence_id=clinic_intelligence_id,
            clinic_account_id=clinic_account_id,
            dedupe_key=(
                f"clinic_cqc:{(clinic_intelligence_id or extract.doctify_url)}:"
                f"{best.location_id or best.location_url or best.name}"
            ),
            dry_run=dry_run,
        )
        return {
            "matched": False,
            "best": best.as_dict(),
            "scraped": False,
            "review_queued": review is not None,
            "review": {"id": (review or {}).get("id"), "confidence": best.confidence},
            "reason": "ambiguous_queued_for_review",
        }

    overview = None
    if best.location_url or best.location_id:
        url = best.location_url or f"https://www.cqc.org.uk/location/{best.location_id}"
        try:
            overview = fetch_location(url)
        except Exception as exc:
            logger.warning("CQC location scrape failed for %s: %s", url, exc)
            overview = None

    payload: dict[str, Any] = {
        "doctify_url": extract.doctify_url,
        "clinic_name": extract.clinic_name or None,
        "cqc_location_id": best.location_id or (overview.location_id if overview else None),
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
        "best": best.as_dict(),
        "scraped": overview is not None,
        "review_queued": False,
        "sync": {"id": sync.get("id")} if isinstance(sync, dict) else sync,
    }


def run_extract_batch(
    items: list[BatchItem],
    *,
    upsert: bool = False,
    dry_run: bool = False,
    headed: bool = False,
    cqc: bool = False,
    refresh_cqc: bool = False,
    preserve_cqc: bool = True,
    delay_s: float = 1.0,
) -> BatchResult:
    """Extract each practice URL with Playwright; optionally upsert + gtm CQC."""
    import time

    result = BatchResult()
    for item in items:
        result.attempted += 1
        url = item.doctify_url
        entry: dict[str, Any] = {"doctify_url": url, "clinic_name": item.clinic_name}
        try:
            extract = extract_practice_sync(url, headless=not headed)
            result.extracted += 1
            entry["listed_specialist_count"] = extract.listed_specialist_count
            entry["visible_clinic_size"] = extract.visible_clinic_size
            entry["founder_score"] = extract.founder_score

            sync_result = None
            if upsert or dry_run:
                sync_result = sync_doctify_extract(
                    extract,
                    dry_run=dry_run or not supabase_configured(),
                    preserve_cqc=preserve_cqc and not refresh_cqc,
                )
                if sync_result and not sync_result.get("dry_run"):
                    result.upserted += 1
                entry["sync"] = {
                    "clinic_intelligence_id": sync_result.get("clinic_intelligence_id"),
                    "people_upserted": sync_result.get("people_upserted"),
                    "dry_run": sync_result.get("dry_run"),
                }

            should_cqc = cqc or refresh_cqc
            if should_cqc and (refresh_cqc or not item.has_cqc or not preserve_cqc):
                cqc_out = _apply_cqc(
                    extract=extract,
                    clinic_intelligence_id=(sync_result or {}).get("clinic_intelligence_id")
                    or item.clinic_intelligence_id,
                    clinic_account_id=(sync_result or {}).get("clinic_account_id"),
                    dry_run=dry_run or not supabase_configured(),
                )
                entry["cqc"] = cqc_out
                if cqc_out.get("matched"):
                    result.cqc_matched += 1
                if cqc_out.get("scraped"):
                    result.cqc_scraped += 1
                if cqc_out.get("review_queued"):
                    result.cqc_review_queued += 1
            elif should_cqc and item.has_cqc and preserve_cqc and not refresh_cqc:
                entry["cqc"] = {"skipped": True, "reason": "preserve_existing_cqc"}

        except Exception as exc:
            logger.exception("extract failed for %s", url)
            entry["error"] = str(exc)
            result.errors.append({"doctify_url": url, "error": str(exc)})

        result.items.append(entry)
        if delay_s > 0:
            time.sleep(delay_s)

    return result
