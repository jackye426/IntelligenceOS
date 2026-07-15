"""In-process background jobs for Railway-triggered GTM runs.

Jobs are process-local (lost on restart). Fine for on-demand triggers;
use ``GET /jobs/{id}`` to poll.
"""

from __future__ import annotations

import logging
import threading
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    with _LOCK:
        items = sorted(_JOBS.values(), key=lambda j: j.get("started_at") or "", reverse=True)
        return [dict(j) for j in items[:limit]]


def start_job(kind: str, fn: Callable[[], dict[str, Any]], *, meta: dict[str, Any] | None = None) -> str:
    job_id = uuid.uuid4().hex[:12]
    record: dict[str, Any] = {
        "id": job_id,
        "kind": kind,
        "status": "queued",
        "started_at": _now(),
        "finished_at": None,
        "meta": meta or {},
        "result": None,
        "error": None,
    }
    with _LOCK:
        _JOBS[job_id] = record

    def _run() -> None:
        with _LOCK:
            _JOBS[job_id]["status"] = "running"
        try:
            result = fn()
            with _LOCK:
                _JOBS[job_id]["status"] = "completed"
                _JOBS[job_id]["result"] = result
                _JOBS[job_id]["finished_at"] = _now()
        except Exception as exc:
            logger.exception("job %s (%s) failed", job_id, kind)
            with _LOCK:
                _JOBS[job_id]["status"] = "failed"
                _JOBS[job_id]["error"] = str(exc)
                _JOBS[job_id]["traceback"] = traceback.format_exc()
                _JOBS[job_id]["finished_at"] = _now()

    threading.Thread(target=_run, name=f"gtm-job-{job_id}", daemon=True).start()
    return job_id


def run_discover(
    *,
    start_url: str = "",
    pages: int | None = None,
    limit: int | None = None,
    listing_delay: float = 2.0,
    use_default_scope: bool = True,
) -> dict[str, Any]:
    from gtm_pipeline.doctify.listing import DEFAULT_SCOPE, discover_listings_sync

    if start_url:
        stubs = discover_listings_sync(
            start_url=start_url,
            pages=pages,
            listing_delay=listing_delay,
            max_total=limit,
        )
    elif use_default_scope:
        if not DEFAULT_SCOPE.exists():
            raise FileNotFoundError(f"Scope CSV missing: {DEFAULT_SCOPE}")
        stubs = discover_listings_sync(
            DEFAULT_SCOPE,
            pages=pages,
            listing_delay=listing_delay,
            max_total=limit,
        )
    else:
        raise ValueError("Provide start_url or use_default_scope=true")

    rows = [s.as_dict() for s in stubs]
    return {"count": len(rows), "stubs": rows, "scope": str(DEFAULT_SCOPE)}


def run_extract_batch(
    *,
    from_supabase: bool = True,
    urls: list[str] | None = None,
    priority: bool = True,
    limit: int | None = 20,
    upsert: bool = True,
    dry_run: bool = False,
    cqc: bool = True,
    refresh_cqc: bool = False,
    delay: float = 1.0,
) -> dict[str, Any]:
    from gtm_pipeline.doctify.extract_batch import (
        BatchItem,
        load_urls_from_supabase,
        run_extract_batch as _batch,
    )
    from gtm_pipeline.shared.supabase_client import supabase_configured

    if urls:
        items = [BatchItem(doctify_url=u.rstrip("/")) for u in urls if u.strip()]
        if limit is not None:
            items = items[:limit]
    elif from_supabase:
        if not supabase_configured() and not dry_run:
            raise RuntimeError("Supabase not configured")
        items = load_urls_from_supabase(priority=priority, limit=limit)
    else:
        raise ValueError("Provide urls or from_supabase=true")

    dry = dry_run or (upsert and not supabase_configured())
    result = _batch(
        items,
        upsert=upsert or dry_run,
        dry_run=dry,
        headed=False,
        cqc=cqc,
        refresh_cqc=refresh_cqc,
        preserve_cqc=not refresh_cqc,
        delay_s=delay,
    )
    return result.as_dict()


def _batch_items_for_enqueue(
    *,
    from_supabase: bool,
    urls: list[str] | None,
    priority: bool,
    limit: int | None,
) -> list[Any]:
    from gtm_pipeline.doctify.extract_batch import BatchItem, load_urls_from_supabase

    if urls:
        items = [BatchItem(doctify_url=u.rstrip("/")) for u in urls if u.strip()]
        if limit is not None:
            items = items[:limit]
        return items
    return load_urls_from_supabase(priority=priority, limit=limit)


def enqueue_extract_batch_durable(
    *,
    from_supabase: bool = True,
    urls: list[str] | None = None,
    priority: bool = True,
    limit: int | None = 20,
    upsert: bool = True,
    dry_run: bool = False,
    cqc: bool = True,
    refresh_cqc: bool = False,
    delay: float = 0.5,
    concurrency: int | None = None,
    start_worker: bool = True,
) -> dict[str, Any]:
    """Create durable job + items; optionally start parallel worker thread."""
    from gtm_pipeline.doctify.extract_batch import BatchItem, run_extract_batch as _batch
    from gtm_pipeline.durable_jobs import (
        create_job,
        extract_concurrency,
        start_durable_job_async,
    )

    items = _batch_items_for_enqueue(
        from_supabase=from_supabase and not urls,
        urls=urls,
        priority=priority,
        limit=limit,
    )
    job_items = [
        {
            "item_key": it.doctify_url,
            "payload": {
                "doctify_url": it.doctify_url,
                "clinic_name": it.clinic_name,
                "clinic_intelligence_id": it.clinic_intelligence_id,
                "has_cqc": it.has_cqc,
                "founder_score": it.founder_score,
            },
        }
        for it in items
        if it.doctify_url
    ]
    params = {
        "upsert": upsert,
        "dry_run": dry_run,
        "cqc": cqc,
        "refresh_cqc": refresh_cqc,
        "delay": delay,
        "priority": priority,
        "from_supabase": from_supabase,
        "concurrency": concurrency or extract_concurrency(),
    }
    job = create_job(
        "doctify_extract_batch",
        params=params,
        meta={"limit": limit, "item_count": len(job_items)},
        items=job_items,
    )
    job_id = job["id"]

    def _handler(item_row: dict[str, Any]) -> dict[str, Any]:
        payload = item_row.get("payload") or {}
        batch_item = BatchItem(
            doctify_url=payload["doctify_url"],
            clinic_name=payload.get("clinic_name") or "",
            clinic_intelligence_id=payload.get("clinic_intelligence_id"),
            has_cqc=bool(payload.get("has_cqc")),
            founder_score=int(payload.get("founder_score") or 0),
        )
        out = _batch(
            [batch_item],
            upsert=upsert,
            dry_run=dry_run,
            headed=False,
            cqc=cqc,
            refresh_cqc=refresh_cqc,
            preserve_cqc=not refresh_cqc,
            delay_s=delay,
        )
        return out.as_dict()

    if start_worker:
        start_durable_job_async(job_id, _handler, concurrency=concurrency)
    return {
        "job_id": job_id,
        "status": "queued",
        "durable": True,
        "poll": f"/jobs/{job_id}",
        "total_items": len(job_items),
        "concurrency": concurrency or extract_concurrency(),
    }


def resume_durable_job(job_id: str, *, concurrency: int | None = None) -> dict[str, Any]:
    """Re-attach a worker to an existing durable job (extract-batch or linkedin_find)."""
    from gtm_pipeline.doctify.extract_batch import BatchItem, run_extract_batch as _batch
    from gtm_pipeline.durable_jobs import get_job, start_durable_job_async
    from gtm_pipeline.linkedin.jobs import linkedin_find_item_handler

    job = get_job(job_id)
    if not job:
        raise ValueError(f"Unknown job {job_id}")
    params = job.get("params") or {}
    kind = job.get("kind") or ""

    if kind == "linkedin_find":
        delay_s = float(params.get("delay_s") or 1.5)
        dry_run = bool(params.get("dry_run", False))

        def _li_handler(item_row: dict[str, Any]) -> dict[str, Any]:
            return linkedin_find_item_handler(
                item_row, dry_run=dry_run, delay_s=delay_s
            )

        start_durable_job_async(job_id, _li_handler, concurrency=concurrency or 1)
        return {"job_id": job_id, "status": "resumed", "poll": f"/jobs/{job_id}"}

    if kind == "rocketreach_enrich":
        from gtm_pipeline.rocketreach.enrich import rocketreach_item_handler

        delay_s = float(params.get("delay_s") or 1.0)
        dry_run = bool(params.get("dry_run", False))

        def _rr_handler(item_row: dict[str, Any]) -> dict[str, Any]:
            return rocketreach_item_handler(
                item_row, dry_run=dry_run, delay_s=delay_s
            )

        start_durable_job_async(job_id, _rr_handler, concurrency=concurrency or 1)
        return {"job_id": job_id, "status": "resumed", "poll": f"/jobs/{job_id}"}

    def _handler(item_row: dict[str, Any]) -> dict[str, Any]:
        payload = item_row.get("payload") or {}
        batch_item = BatchItem(
            doctify_url=payload["doctify_url"],
            clinic_name=payload.get("clinic_name") or "",
            clinic_intelligence_id=payload.get("clinic_intelligence_id"),
            has_cqc=bool(payload.get("has_cqc")),
            founder_score=int(payload.get("founder_score") or 0),
        )
        out = _batch(
            [batch_item],
            upsert=bool(params.get("upsert", True)),
            dry_run=bool(params.get("dry_run", False)),
            headed=False,
            cqc=bool(params.get("cqc", True)),
            refresh_cqc=bool(params.get("refresh_cqc", False)),
            preserve_cqc=not bool(params.get("refresh_cqc", False)),
            delay_s=float(params.get("delay") or 0.5),
        )
        return out.as_dict()

    start_durable_job_async(job_id, _handler, concurrency=concurrency)
    return {"job_id": job_id, "status": "resumed", "poll": f"/jobs/{job_id}"}


def run_scoped_pipeline(
    *,
    start_url: str = "",
    pages: int | None = None,
    discover_limit: int | None = 20,
    extract_limit: int | None = None,
    listing_delay: float = 2.0,
    extract_delay: float = 1.0,
    upsert: bool = True,
    dry_run: bool = False,
    cqc: bool = True,
    refresh_cqc: bool = False,
    skip_discover: bool = False,
    from_supabase: bool = False,
    priority: bool = True,
) -> dict[str, Any]:
    """discover (optional) → extract-batch → optional CQC."""
    out: dict[str, Any] = {"discover": None, "extract_batch": None}

    urls: list[str] = []
    if skip_discover or from_supabase:
        out["discover"] = {"skipped": True, "reason": "from_supabase" if from_supabase else "skip_discover"}
        batch = run_extract_batch(
            from_supabase=True,
            priority=priority,
            limit=extract_limit if extract_limit is not None else discover_limit,
            upsert=upsert,
            dry_run=dry_run,
            cqc=cqc,
            refresh_cqc=refresh_cqc,
            delay=extract_delay,
        )
        out["extract_batch"] = batch
        return out

    disc = run_discover(
        start_url=start_url,
        pages=pages,
        limit=discover_limit,
        listing_delay=listing_delay,
        use_default_scope=not bool(start_url),
    )
    out["discover"] = {"count": disc["count"]}
    urls = [s["doctify_url"] for s in disc["stubs"] if s.get("doctify_url")]
    if extract_limit is not None:
        urls = urls[:extract_limit]

    batch = run_extract_batch(
        from_supabase=False,
        urls=urls,
        limit=None,
        upsert=upsert,
        dry_run=dry_run,
        cqc=cqc,
        refresh_cqc=refresh_cqc,
        delay=extract_delay,
    )
    out["extract_batch"] = batch
    return out
