"""Durable LinkedIn find jobs (outreach contacts — everyone missing URL)."""

from __future__ import annotations

import logging
import time
from typing import Any

from gtm_pipeline.linkedin.find import find_and_apply_for_person
from gtm_pipeline.segments import get_cohort, list_members
from gtm_pipeline.shared.supabase_client import get_client

logger = logging.getLogger(__name__)


def linkedin_find_item_handler(
    item_row: dict[str, Any],
    *,
    dry_run: bool = False,
    delay_s: float = 0.0,
) -> dict[str, Any]:
    payload = item_row.get("payload") or {}
    out = find_and_apply_for_person(
        person_id=payload.get("person_id"),
        person_name=payload.get("person_name") or "",
        clinic_name=payload.get("clinic_name") or "",
        clinic_intelligence_id=payload.get("clinic_intelligence_id"),
        clinic_account_id=payload.get("clinic_account_id"),
        dry_run=dry_run,
        contact_id=payload.get("contact_id"),
    )
    if delay_s:
        time.sleep(delay_s)
    return out


def enqueue_linkedin_find_durable(
    slug: str | None = None,
    *,
    cohort: str | None = None,
    limit: int = 20,
    delay_s: float = 1.5,
    dry_run: bool = False,
    force: bool = False,
    start_worker: bool = True,
    concurrency: int | None = 1,
) -> dict[str, Any]:
    """Durable job: one item per outreach contact missing LinkedIn URL."""
    from gtm_pipeline.durable_jobs import create_job, start_durable_job_async

    cohort_slug = cohort or slug
    clinic_filter: set[str] | None = None
    if cohort_slug:
        if not get_cohort(cohort_slug):
            raise ValueError(f"Unknown cohort: {cohort_slug}")
        members = list_members(cohort_slug, limit=5000)["members"]
        clinic_filter = {
            m["clinic_intelligence_id"] for m in members if m.get("clinic_intelligence_id")
        }

    client = get_client()
    rows = (
        client.table("gtm_outreach_contacts")
        .select("*")
        .order("founder_score", desc=True)
        .limit(max(limit * 5, limit))
        .execute()
        .data
        or []
    )

    job_items: list[dict[str, Any]] = []
    for contact in rows:
        if clinic_filter is not None and contact["clinic_intelligence_id"] not in clinic_filter:
            continue
        if not force and (contact.get("linkedin_url") or "").strip():
            continue
        intel = (
            client.table("gtm_clinic_intelligence")
            .select("clinic_name")
            .eq("id", contact["clinic_intelligence_id"])
            .limit(1)
            .execute()
            .data
            or []
        )
        job_items.append(
            {
                "item_key": contact["id"],
                "payload": {
                    "contact_id": contact["id"],
                    "person_id": contact.get("person_id"),
                    "person_name": contact.get("full_name") or "",
                    "clinic_name": (intel[0].get("clinic_name") if intel else "") or "",
                    "clinic_intelligence_id": contact["clinic_intelligence_id"],
                    "clinic_account_id": contact.get("clinic_account_id"),
                },
            }
        )
        if len(job_items) >= limit:
            break

    params = {
        "cohort": cohort_slug,
        "delay_s": delay_s,
        "dry_run": dry_run,
        "limit": limit,
        "force": force,
    }
    job = create_job(
        "linkedin_find",
        params=params,
        meta={"cohort": cohort_slug, "item_count": len(job_items)},
        items=job_items,
    )
    job_id = job["id"]

    def _handler(item_row: dict[str, Any]) -> dict[str, Any]:
        return linkedin_find_item_handler(
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
        "cohort": cohort_slug,
    }
