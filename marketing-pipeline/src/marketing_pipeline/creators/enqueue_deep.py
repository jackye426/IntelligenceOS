"""Enqueue Warren-depth jobs for every good-fit profile. Idempotent on profile id."""

from __future__ import annotations

from typing import Any

from marketing_pipeline.creators.good_fit import deep_priority, is_good_fit
from marketing_pipeline.creators.store import get_store


def _open_job(kind: str, store) -> dict[str, Any]:
    existing = [j for j in store.list("creator_deep_jobs", kind=kind) if j.get("status") in {"queued", "running"}]
    if existing:
        return existing[0]
    return store.insert(
        "creator_deep_jobs",
        {"kind": kind, "status": "running", "params": {}, "meta": {"standing": True}},
    )


def enqueue_deep(*, store=None, quality: str = "auto") -> dict[str, int]:
    store = store or get_store()
    ingest_job = _open_job("deep_ingest", store)
    inserted = 0
    skipped = 0
    for profile in store.list("creator_profiles"):
        if not is_good_fit(profile):
            continue
        if profile.get("deep_status") in {"ingested", "brief_draft", "brief_confirmed", "ingesting", "queued"}:
            skipped += 1
            continue
        item = store.upsert(
            "creator_deep_job_items",
            {
                "job_id": ingest_job["id"],
                "kind": "deep_ingest",
                "item_key": profile["id"],
                "priority": deep_priority(profile),
                "payload": {"handle": profile["handle"], "quality": quality},
                "status": "queued",
            },
            keys=("kind", "item_key"),
        )
        store.update(
            "creator_profiles",
            {
                "deep_status": "queued",
                "deep_quality": quality,
                "deep_job_id": item.get("id"),
                "good_fit": True,
            },
            id=profile["id"],
        )
        inserted += 1
    return {"enqueued": inserted, "skipped": skipped}
