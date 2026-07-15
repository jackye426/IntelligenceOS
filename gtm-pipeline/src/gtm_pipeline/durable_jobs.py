"""Durable GTM pipeline jobs backed by Supabase (claim + heartbeat + parallel)."""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable

from gtm_pipeline.shared.supabase_client import get_client, supabase_configured

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def worker_id() -> str:
    return os.getenv("RAILWAY_REPLICA_ID") or f"{socket.gethostname()}-{os.getpid()}"


def extract_concurrency() -> int:
    raw = os.getenv("GTM_EXTRACT_CONCURRENCY", "3").strip()
    try:
        return max(1, min(8, int(raw)))
    except ValueError:
        return 3


def stale_seconds() -> int:
    raw = os.getenv("GTM_JOB_STALE_SECONDS", "600").strip()
    try:
        return max(60, int(raw))
    except ValueError:
        return 600


def create_job(
    kind: str,
    *,
    params: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create job + optional items. Each item needs item_key + payload."""
    if not supabase_configured():
        raise RuntimeError("Supabase required for durable jobs")

    client = get_client()
    job_row = {
        "kind": kind,
        "status": "queued",
        "params": params or {},
        "meta": meta or {},
        "total_items": len(items or []),
        "updated_at": _now(),
    }
    inserted = client.table("gtm_pipeline_jobs").insert(job_row).execute().data or []
    if not inserted:
        raise RuntimeError("Failed to create gtm_pipeline_jobs row")
    job = inserted[0]
    job_id = job["id"]

    if items:
        chunk: list[dict[str, Any]] = []
        for it in items:
            chunk.append(
                {
                    "job_id": job_id,
                    "item_key": it["item_key"],
                    "payload": it.get("payload") or {},
                    "status": "queued",
                    "updated_at": _now(),
                }
            )
            if len(chunk) >= 200:
                client.table("gtm_pipeline_job_items").upsert(
                    chunk, on_conflict="job_id,item_key"
                ).execute()
                chunk = []
        if chunk:
            client.table("gtm_pipeline_job_items").upsert(
                chunk, on_conflict="job_id,item_key"
            ).execute()

    return job


def get_job(job_id: str) -> dict[str, Any] | None:
    if not supabase_configured():
        return None
    client = get_client()
    rows = (
        client.table("gtm_pipeline_jobs").select("*").eq("id", job_id).limit(1).execute().data
        or []
    )
    if not rows:
        return None
    job = rows[0]
    # Attach item status counts
    items = (
        client.table("gtm_pipeline_job_items")
        .select("status")
        .eq("job_id", job_id)
        .execute()
        .data
        or []
    )
    counts: dict[str, int] = {}
    for it in items:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    job["item_counts"] = counts
    return job


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    if not supabase_configured():
        return []
    client = get_client()
    return (
        client.table("gtm_pipeline_jobs")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )


def claim_items(job_id: str, *, limit: int, worker: str | None = None) -> list[dict[str, Any]]:
    client = get_client()
    wid = worker or worker_id()
    try:
        rows = client.rpc(
            "gtm_claim_job_items",
            {
                "p_job_id": job_id,
                "p_limit": limit,
                "p_worker_id": wid,
                "p_stale_seconds": stale_seconds(),
            },
        ).execute().data
        return rows or []
    except Exception:
        logger.exception("gtm_claim_job_items RPC failed; falling back to optimistic claim")
        return _optimistic_claim(job_id, limit=limit, worker=wid)


def _optimistic_claim(job_id: str, *, limit: int, worker: str) -> list[dict[str, Any]]:
    client = get_client()
    # Reclaim stale
    stale_iso = datetime.fromtimestamp(
        time.time() - stale_seconds(), tz=timezone.utc
    ).replace(microsecond=0).isoformat()
    running = (
        client.table("gtm_pipeline_job_items")
        .select("id, heartbeat_at")
        .eq("job_id", job_id)
        .eq("status", "running")
        .limit(200)
        .execute()
        .data
        or []
    )
    for row in running:
        hb = row.get("heartbeat_at") or ""
        if not hb or hb < stale_iso:
            client.table("gtm_pipeline_job_items").update(
                {
                    "status": "queued",
                    "worker_id": None,
                    "claimed_at": None,
                    "heartbeat_at": None,
                    "updated_at": _now(),
                }
            ).eq("id", row["id"]).eq("status", "running").execute()

    queued = (
        client.table("gtm_pipeline_job_items")
        .select("id")
        .eq("job_id", job_id)
        .eq("status", "queued")
        .order("created_at")
        .limit(limit)
        .execute()
        .data
        or []
    )
    claimed: list[dict[str, Any]] = []
    for row in queued:
        updated = (
            client.table("gtm_pipeline_job_items")
            .update(
                {
                    "status": "running",
                    "worker_id": worker,
                    "claimed_at": _now(),
                    "heartbeat_at": _now(),
                    "updated_at": _now(),
                }
            )
            .eq("id", row["id"])
            .eq("status", "queued")
            .execute()
            .data
            or []
        )
        # attempts++
        if updated:
            att = int(updated[0].get("attempts") or 0) + 1
            refreshed = (
                client.table("gtm_pipeline_job_items")
                .update({"attempts": att, "updated_at": _now()})
                .eq("id", row["id"])
                .execute()
                .data
                or []
            )
            claimed.append(refreshed[0] if refreshed else updated[0])
    return claimed


def heartbeat_item(item_id: str) -> None:
    get_client().table("gtm_pipeline_job_items").update(
        {"heartbeat_at": _now(), "updated_at": _now()}
    ).eq("id", item_id).execute()


def complete_item(
    item_id: str,
    *,
    ok: bool,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    get_client().table("gtm_pipeline_job_items").update(
        {
            "status": "succeeded" if ok else "failed",
            "result": result or {},
            "error": error,
            "finished_at": _now(),
            "heartbeat_at": _now(),
            "updated_at": _now(),
        }
    ).eq("id", item_id).execute()


def refresh_job_counters(job_id: str) -> dict[str, Any]:
    client = get_client()
    items = (
        client.table("gtm_pipeline_job_items")
        .select("status")
        .eq("job_id", job_id)
        .execute()
        .data
        or []
    )
    succeeded = sum(1 for i in items if i["status"] == "succeeded")
    failed = sum(1 for i in items if i["status"] == "failed")
    active = sum(1 for i in items if i["status"] in ("queued", "running"))
    total = len(items)
    payload: dict[str, Any] = {
        "succeeded_items": succeeded,
        "failed_items": failed,
        "total_items": total,
        "updated_at": _now(),
    }
    if total == 0:
        payload["status"] = "completed"
        payload["finished_at"] = _now()
    elif active == 0:
        payload["status"] = "completed" if succeeded > 0 or failed == 0 else "failed"
        if failed and succeeded == 0:
            payload["status"] = "failed"
        payload["finished_at"] = _now()
    else:
        payload["status"] = "running"
        payload["started_at"] = _now()
    updated = (
        client.table("gtm_pipeline_jobs").update(payload).eq("id", job_id).execute().data or []
    )
    return updated[0] if updated else payload


def mark_job_running(job_id: str) -> None:
    get_client().table("gtm_pipeline_jobs").update(
        {"status": "running", "started_at": _now(), "updated_at": _now()}
    ).eq("id", job_id).eq("status", "queued").execute()


def process_job_items(
    job_id: str,
    handler: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    concurrency: int | None = None,
    batch_claim: int | None = None,
) -> dict[str, Any]:
    """Claim and process items until the job queue is drained."""
    conc = concurrency or extract_concurrency()
    claim_n = batch_claim or max(conc * 2, conc)
    mark_job_running(job_id)
    wid = worker_id()
    processed = 0

    def _one(item: dict[str, Any]) -> None:
        nonlocal processed
        try:
            heartbeat_item(item["id"])
            result = handler(item)
            complete_item(item["id"], ok=True, result=result)
        except Exception as exc:
            logger.exception("job item %s failed", item.get("id"))
            complete_item(item["id"], ok=False, error=str(exc))
        processed += 1

    while True:
        claimed = claim_items(job_id, limit=claim_n, worker=wid)
        if not claimed:
            break
        if conc <= 1:
            for item in claimed:
                _one(item)
        else:
            with ThreadPoolExecutor(max_workers=conc) as pool:
                futs = [pool.submit(_one, item) for item in claimed]
                for f in as_completed(futs):
                    f.result()
        refresh_job_counters(job_id)

    job = refresh_job_counters(job_id)
    return {"job_id": job_id, "processed": processed, "job": job}


def start_durable_job_async(
    job_id: str,
    handler: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    concurrency: int | None = None,
) -> str:
    """Background thread that drains a durable job (survives API return; not process restart)."""

    def _run() -> None:
        try:
            process_job_items(job_id, handler, concurrency=concurrency)
        except Exception:
            logger.exception("durable job %s crashed", job_id)
            try:
                get_client().table("gtm_pipeline_jobs").update(
                    {
                        "status": "failed",
                        "error": "worker crashed — see logs; remaining items reclaimable",
                        "finished_at": _now(),
                        "updated_at": _now(),
                    }
                ).eq("id", job_id).execute()
            except Exception:
                logger.exception("failed to mark job %s failed", job_id)

    threading.Thread(target=_run, name=f"gtm-durable-{job_id[:8]}", daemon=True).start()
    return job_id
