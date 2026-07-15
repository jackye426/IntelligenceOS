"""HTTP service for GTM Account Intelligence scrapes (Railway).

Local:
  uvicorn gtm_pipeline.service:app --reload --port 8080

Auth: set GTM_SERVICE_TOKEN (or reuse MCP_AUTH_TOKEN). Send
  Authorization: Bearer <token>
on mutating endpoints. /health is open.

Long runs (discover / extract-batch / scoped-run) default to background jobs —
poll ``GET /jobs/{id}``. Extract-batch prefers **durable** Supabase jobs
(``gtm_pipeline_jobs`` / ``gtm_pipeline_job_items``) with parallel workers
(``GTM_EXTRACT_CONCURRENCY``, default 3) and ``POST /jobs/{id}/resume``.
"""

from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from gtm_pipeline import config

logger = logging.getLogger("gtm_pipeline.service")


def _auto_refresh_on_startup() -> bool:
    return os.getenv("CQC_DIRECTORY_AUTO_REFRESH", "1").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if _auto_refresh_on_startup():
        try:
            from gtm_pipeline.cqc_directory.refresh import download_directory

            status = download_directory(force=False)
            logger.info(
                "CQC directory startup: exists=%s refreshed=%s age_days=%s path=%s err=%s",
                status.exists,
                status.refreshed,
                status.age_days,
                status.path,
                status.error or "",
            )
        except Exception:
            logger.exception(
                "CQC directory startup refresh failed (match will retry on demand)"
            )
    yield


app = FastAPI(title="GTM Pipeline", version="0.1.0", lifespan=lifespan)


def _expected_token() -> str:
    return (
        os.getenv("GTM_SERVICE_TOKEN")
        or os.getenv("MCP_AUTH_TOKEN")
        or ""
    ).strip()


async def require_auth(authorization: str | None = Header(default=None)) -> None:
    expected = _expected_token()
    if not expected:
        if os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("GTM_REQUIRE_AUTH", "").lower() in {
            "1",
            "true",
            "yes",
        }:
            raise HTTPException(status_code=503, detail="GTM_SERVICE_TOKEN not configured")
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    got = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(got, expected):
        raise HTTPException(status_code=401, detail="Invalid token")


def _dispatch(kind: str, background: bool, meta: dict[str, Any], fn) -> dict[str, Any]:
    """In-memory fallback jobs (discover). Extract-batch prefers durable Supabase jobs."""
    from gtm_pipeline.pipeline_jobs import start_job

    if background:
        job_id = start_job(kind, fn, meta=meta)
        return {
            "job_id": job_id,
            "status": "queued",
            "durable": False,
            "poll": f"/jobs/{job_id}",
        }
    return fn()


# --- request bodies ---------------------------------------------------------


class DoctifyExtractBody(BaseModel):
    url: str = Field(default=config.DOCTIFY_FIXTURE_URL)
    upsert: bool = True
    dry_run: bool = False


class DoctifyDiscoverBody(BaseModel):
    start_url: str = ""
    pages: int | None = None
    limit: int | None = Field(default=20, description="Max practice stubs (keep small on first runs)")
    listing_delay: float = 2.0
    use_default_scope: bool = True
    background: bool = True


class DoctifyExtractBatchBody(BaseModel):
    from_supabase: bool = True
    urls: list[str] = Field(default_factory=list)
    priority: bool = True
    limit: int | None = Field(default=20, description="Cap practices per trigger")
    upsert: bool = True
    dry_run: bool = False
    cqc: bool = True
    refresh_cqc: bool = False
    delay: float = 0.5
    background: bool = True
    durable: bool = True
    concurrency: int | None = Field(
        default=None, description="Parallel Playwright workers (default GTM_EXTRACT_CONCURRENCY=3)"
    )


class ScopedRunBody(BaseModel):
    """Full GTM slice: discover listing → extract → CQC (or supabase backfill)."""

    start_url: str = ""
    pages: int | None = None
    discover_limit: int | None = 20
    extract_limit: int | None = None
    listing_delay: float = 2.0
    extract_delay: float = 0.5
    upsert: bool = True
    dry_run: bool = False
    cqc: bool = True
    refresh_cqc: bool = False
    from_supabase: bool = False
    priority: bool = True
    skip_discover: bool = False
    background: bool = True
    durable: bool = True
    concurrency: int | None = None


class OwnersScanBody(BaseModel):
    limit: int | None = None
    dry_run: bool = False


class CqcMatchBody(BaseModel):
    name: str
    postcode: str = ""
    address: str = ""
    website: str = ""
    phone: str = ""
    top: int = 5


class CqcLocationBody(BaseModel):
    url: str = "https://www.cqc.org.uk/location/1-19271937885"
    upsert: bool = False
    dry_run: bool = False
    clinic_account_id: str | None = None
    doctify_url: str | None = None


class CqcRefreshBody(BaseModel):
    force: bool = False


class SegmentsRefreshBody(BaseModel):
    slug: str | None = None
    dry_run: bool = False


class ContactsPrepareBody(BaseModel):
    cohort: str
    limit: int | None = 50
    dry_run: bool = False
    skip_cqc: bool = False
    skip_people: bool = False
    force_cqc: bool = False


class LinkedInFindBody(BaseModel):
    cohort: str | None = None
    limit: int = 20
    delay: float = 1.5
    dry_run: bool = False
    sync: bool = False
    force: bool = False


class OutreachRefreshBody(BaseModel):
    cohort: str | None = None
    limit: int | None = None
    dry_run: bool = False
    cqc_named_only: bool = True


class RocketReachBody(BaseModel):
    cohort: str | None = None
    limit: int = 20
    delay: float = 1.0
    dry_run: bool = False
    sync: bool = False
    force: bool = False


# --- routes -----------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, Any]:
    from gtm_pipeline.cqc_directory.refresh import directory_status
    from gtm_pipeline.doctify.listing import DEFAULT_SCOPE

    cqc = directory_status()
    return {
        "ok": True,
        "service": "gtm-pipeline",
        "supabase_configured": bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_ROLE_KEY),
        "auth_configured": bool(_expected_token()),
        "cqc_directory": cqc.as_dict(),
        "doctify_scope_csv": {
            "path": str(DEFAULT_SCOPE),
            "exists": DEFAULT_SCOPE.exists(),
        },
    }


@app.get("/jobs", dependencies=[Depends(require_auth)])
def jobs_list(limit: int = 20) -> dict[str, Any]:
    from gtm_pipeline.durable_jobs import list_jobs as list_durable
    from gtm_pipeline.pipeline_jobs import list_jobs as list_memory
    from gtm_pipeline.shared.supabase_client import supabase_configured

    durable = list_durable(limit=limit) if supabase_configured() else []
    memory = list_memory(limit=limit)
    return {"jobs": durable, "in_memory_jobs": memory}


@app.get("/jobs/{job_id}", dependencies=[Depends(require_auth)])
def jobs_get(job_id: str) -> dict[str, Any]:
    from gtm_pipeline.durable_jobs import get_job as get_durable
    from gtm_pipeline.pipeline_jobs import get_job as get_memory
    from gtm_pipeline.shared.supabase_client import supabase_configured

    if supabase_configured():
        # UUID durable ids vs short hex memory ids
        if len(job_id) >= 32 or "-" in job_id:
            job = get_durable(job_id)
            if job:
                job["durable"] = True
                return job
    job = get_memory(job_id)
    if not job:
        # try durable anyway
        if supabase_configured():
            job = get_durable(job_id)
            if job:
                job["durable"] = True
                return job
        raise HTTPException(status_code=404, detail="Unknown job_id")
    job["durable"] = False
    return job


@app.post("/jobs/{job_id}/resume", dependencies=[Depends(require_auth)])
def jobs_resume(job_id: str, concurrency: int | None = None) -> dict[str, Any]:
    from gtm_pipeline.pipeline_jobs import resume_durable_job

    try:
        return resume_durable_job(job_id, concurrency=concurrency)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/match-reviews/pending", dependencies=[Depends(require_auth)])
def match_reviews_pending(
    clinic_intelligence_id: str | None = None,
    clinic_account_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    from gtm_pipeline.sync.match_reviews import list_pending_reviews_for_clinic
    from gtm_pipeline.shared.supabase_client import get_client, supabase_configured

    if clinic_intelligence_id or clinic_account_id:
        rows = list_pending_reviews_for_clinic(
            clinic_intelligence_id=clinic_intelligence_id,
            clinic_account_id=clinic_account_id,
            limit=limit,
        )
        return {"reviews": rows, "count": len(rows)}

    if not supabase_configured():
        return {"reviews": [], "count": 0}
    rows = (
        get_client()
        .table("gtm_match_reviews")
        .select("*")
        .eq("status", "pending")
        .order("confidence", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    return {"reviews": rows, "count": len(rows)}


@app.post("/doctify/extract", dependencies=[Depends(require_auth)])
def doctify_extract(body: DoctifyExtractBody) -> dict[str, Any]:
    from gtm_pipeline.doctify.extract import extract_practice_sync
    from gtm_pipeline.shared.supabase_client import supabase_configured
    from gtm_pipeline.sync.clinic_intelligence import sync_doctify_extract

    logger.info("doctify extract url=%s upsert=%s", body.url, body.upsert)
    extract = extract_practice_sync(body.url, headless=True)
    sync_result = None
    if body.upsert or body.dry_run:
        dry = body.dry_run or not supabase_configured()
        sync_result = sync_doctify_extract(extract, dry_run=dry)
    return {"extract": extract.to_dict(), "sync": sync_result}


@app.post("/doctify/discover", dependencies=[Depends(require_auth)])
def doctify_discover(body: DoctifyDiscoverBody) -> dict[str, Any]:
    from gtm_pipeline.pipeline_jobs import run_discover

    logger.info(
        "doctify discover start_url=%s limit=%s background=%s",
        body.start_url or "(scope)",
        body.limit,
        body.background,
    )

    def _fn() -> dict[str, Any]:
        return run_discover(
            start_url=body.start_url,
            pages=body.pages,
            limit=body.limit,
            listing_delay=body.listing_delay,
            use_default_scope=body.use_default_scope,
        )

    return _dispatch(
        "doctify_discover",
        body.background,
        {"limit": body.limit, "start_url": body.start_url},
        _fn,
    )


@app.post("/doctify/extract-batch", dependencies=[Depends(require_auth)])
def doctify_extract_batch(body: DoctifyExtractBatchBody) -> dict[str, Any]:
    from gtm_pipeline.pipeline_jobs import enqueue_extract_batch_durable, run_extract_batch
    from gtm_pipeline.shared.supabase_client import supabase_configured

    logger.info(
        "doctify extract-batch from_supabase=%s urls=%s limit=%s durable=%s background=%s",
        body.from_supabase,
        len(body.urls),
        body.limit,
        body.durable,
        body.background,
    )

    use_durable = body.durable and body.background and supabase_configured()
    if use_durable:
        try:
            return enqueue_extract_batch_durable(
                from_supabase=body.from_supabase and not body.urls,
                urls=body.urls or None,
                priority=body.priority,
                limit=body.limit,
                upsert=body.upsert,
                dry_run=body.dry_run,
                cqc=body.cqc,
                refresh_cqc=body.refresh_cqc,
                delay=body.delay,
                concurrency=body.concurrency,
                start_worker=True,
            )
        except Exception:
            logger.exception("durable enqueue failed; falling back to in-memory job")

    def _fn() -> dict[str, Any]:
        return run_extract_batch(
            from_supabase=body.from_supabase and not body.urls,
            urls=body.urls or None,
            priority=body.priority,
            limit=body.limit,
            upsert=body.upsert,
            dry_run=body.dry_run,
            cqc=body.cqc,
            refresh_cqc=body.refresh_cqc,
            delay=body.delay,
        )

    return _dispatch(
        "doctify_extract_batch",
        body.background,
        {"limit": body.limit, "from_supabase": body.from_supabase, "cqc": body.cqc},
        _fn,
    )


@app.post("/pipeline/scoped-run", dependencies=[Depends(require_auth)])
def pipeline_scoped_run(body: ScopedRunBody) -> dict[str, Any]:
    from gtm_pipeline.pipeline_jobs import (
        enqueue_extract_batch_durable,
        run_discover,
        run_scoped_pipeline,
    )
    from gtm_pipeline.shared.supabase_client import supabase_configured

    logger.info(
        "pipeline scoped-run from_supabase=%s discover_limit=%s durable=%s",
        body.from_supabase,
        body.discover_limit,
        body.durable,
    )

    if (
        body.durable
        and body.background
        and supabase_configured()
        and (body.from_supabase or body.skip_discover)
    ):
        try:
            return enqueue_extract_batch_durable(
                from_supabase=True,
                priority=body.priority,
                limit=body.extract_limit
                if body.extract_limit is not None
                else body.discover_limit,
                upsert=body.upsert,
                dry_run=body.dry_run,
                cqc=body.cqc,
                refresh_cqc=body.refresh_cqc,
                delay=body.extract_delay,
                concurrency=body.concurrency,
                start_worker=True,
            )
        except Exception:
            logger.exception("durable scoped-run enqueue failed; falling back")

    def _fn() -> dict[str, Any]:
        if body.start_url and not body.from_supabase and not body.skip_discover:
            disc = run_discover(
                start_url=body.start_url,
                pages=body.pages,
                limit=body.discover_limit,
                listing_delay=body.listing_delay,
                use_default_scope=False,
            )
            urls = [s["doctify_url"] for s in disc.get("stubs") or [] if s.get("doctify_url")]
            if body.extract_limit is not None:
                urls = urls[: body.extract_limit]
            if body.durable and supabase_configured() and urls:
                enq = enqueue_extract_batch_durable(
                    from_supabase=False,
                    urls=urls,
                    limit=None,
                    upsert=body.upsert,
                    dry_run=body.dry_run,
                    cqc=body.cqc,
                    refresh_cqc=body.refresh_cqc,
                    delay=body.extract_delay,
                    concurrency=body.concurrency,
                    start_worker=True,
                )
                return {"discover": {"count": disc.get("count")}, "extract_batch": enq}
        return run_scoped_pipeline(
            start_url=body.start_url,
            pages=body.pages,
            discover_limit=body.discover_limit,
            extract_limit=body.extract_limit,
            listing_delay=body.listing_delay,
            extract_delay=body.extract_delay,
            upsert=body.upsert,
            dry_run=body.dry_run,
            cqc=body.cqc,
            refresh_cqc=body.refresh_cqc,
            skip_discover=body.skip_discover,
            from_supabase=body.from_supabase,
            priority=body.priority,
        )

    return _dispatch(
        "pipeline_scoped_run",
        body.background,
        {
            "discover_limit": body.discover_limit,
            "from_supabase": body.from_supabase,
            "cqc": body.cqc,
        },
        _fn,
    )


@app.post("/owners/scan", dependencies=[Depends(require_auth)])
def owners_scan(body: OwnersScanBody) -> dict[str, Any]:
    from gtm_pipeline.owner_discovery import discover_owners

    logger.info("owners scan limit=%s dry_run=%s", body.limit, body.dry_run)
    return discover_owners(dry_run=body.dry_run, limit=body.limit)


@app.post("/cqc/refresh-directory", dependencies=[Depends(require_auth)])
def cqc_refresh_directory(body: CqcRefreshBody) -> dict[str, Any]:
    from gtm_pipeline.cqc_directory.refresh import download_directory

    status = download_directory(force=body.force)
    if not status.exists:
        raise HTTPException(
            status_code=502,
            detail=status.error or "CQC directory download failed",
        )
    return status.as_dict()


@app.post("/cqc/match", dependencies=[Depends(require_auth)])
def cqc_match(body: CqcMatchBody) -> dict[str, Any]:
    from gtm_pipeline.cqc_directory import match_directory

    hits = match_directory(
        name=body.name,
        postcode=body.postcode,
        address=body.address,
        website=body.website,
        phone=body.phone,
        top_k=body.top,
    )
    return {"candidates": [h.as_dict() for h in hits]}


@app.post("/cqc/location", dependencies=[Depends(require_auth)])
def cqc_location(body: CqcLocationBody) -> dict[str, Any]:
    from gtm_pipeline.cqc_location import fetch_location
    from gtm_pipeline.shared.supabase_client import supabase_configured
    from gtm_pipeline.sync.clinic_intelligence import upsert_clinic_intelligence

    overview = fetch_location(body.url)
    sync_result = None
    if body.upsert or body.dry_run:
        dry = body.dry_run or not supabase_configured()
        payload = {
            "clinic_account_id": body.clinic_account_id,
            "doctify_url": body.doctify_url,
            "clinic_name": overview.name or None,
            "cqc_location_id": overview.location_id,
            "cqc_location_url": overview.location_url,
            "cqc_registered_since": overview.registered_since.isoformat()
            if overview.registered_since
            else None,
            "cqc_specialisms": overview.specialisms,
            "cqc_registered_manager": overview.registered_manager or None,
            "cqc_nominated_individual": overview.nominated_individual or None,
            "cqc_provider_name": overview.provider_name or None,
            "evidence": overview.evidence,
            "provenance": overview.provenance,
        }
        sync_result = upsert_clinic_intelligence(payload, dry_run=dry)
    return {"overview": overview.to_dict(), "sync": sync_result}


@app.post("/segments/refresh", dependencies=[Depends(require_auth)])
def segments_refresh(body: SegmentsRefreshBody) -> dict[str, Any]:
    from gtm_pipeline.segments import refresh_all_cohorts, refresh_cohort

    if body.slug:
        return refresh_cohort(body.slug, dry_run=body.dry_run)
    return refresh_all_cohorts(dry_run=body.dry_run)


@app.get("/segments/{slug}/members", dependencies=[Depends(require_auth)])
def segments_members(
    slug: str,
    status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    from gtm_pipeline.segments import list_members

    try:
        return list_members(slug, status=status, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/segments", dependencies=[Depends(require_auth)])
def segments_list_cohorts(active_only: bool = True) -> dict[str, Any]:
    from gtm_pipeline.segments import list_cohorts

    rows = list_cohorts(active_only=active_only)
    return {"cohorts": rows, "count": len(rows)}


@app.post("/contacts/prepare", dependencies=[Depends(require_auth)])
def contacts_prepare(body: ContactsPrepareBody) -> dict[str, Any]:
    from gtm_pipeline.contacts import prepare_cohort_contacts

    try:
        return prepare_cohort_contacts(
            body.cohort,
            limit=body.limit,
            dry_run=body.dry_run,
            skip_cqc=body.skip_cqc,
            skip_people=body.skip_people,
            force_cqc=body.force_cqc,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/contacts/refresh-outreach", dependencies=[Depends(require_auth)])
def contacts_refresh_outreach(body: OutreachRefreshBody) -> dict[str, Any]:
    from gtm_pipeline.contacts import refresh_outreach_contacts

    try:
        return refresh_outreach_contacts(
            cqc_named_only=body.cqc_named_only,
            cohort=body.cohort,
            limit=body.limit,
            dry_run=body.dry_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/contacts/outreach", dependencies=[Depends(require_auth)])
def contacts_outreach_list(
    status: str | None = None,
    preferred_channel: str | None = None,
    ready_sales: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    from gtm_pipeline.contacts import list_outreach_contacts, list_ready_for_sales

    if ready_sales:
        return list_ready_for_sales(limit=limit)
    return list_outreach_contacts(
        status=status, preferred_channel=preferred_channel, limit=limit
    )


@app.post("/contacts/rocketreach", dependencies=[Depends(require_auth)])
def contacts_rocketreach(body: RocketReachBody) -> dict[str, Any]:
    from gtm_pipeline.rocketreach import (
        enqueue_rocketreach_durable,
        rocketreach_enrich_contacts,
    )
    from gtm_pipeline.shared.supabase_client import supabase_configured

    try:
        if body.sync or body.dry_run or not supabase_configured():
            return rocketreach_enrich_contacts(
                limit=body.limit,
                cohort=body.cohort,
                delay_s=body.delay,
                dry_run=body.dry_run,
                force=body.force,
            )
        return enqueue_rocketreach_durable(
            limit=body.limit,
            cohort=body.cohort,
            delay_s=body.delay,
            dry_run=False,
            force=body.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/contacts/linkedin-find", dependencies=[Depends(require_auth)])
def contacts_linkedin_find(body: LinkedInFindBody) -> dict[str, Any]:
    from gtm_pipeline.linkedin.find import linkedin_find_for_contacts
    from gtm_pipeline.linkedin.jobs import enqueue_linkedin_find_durable
    from gtm_pipeline.shared.supabase_client import supabase_configured

    try:
        if body.sync or body.dry_run or not supabase_configured():
            return linkedin_find_for_contacts(
                limit=body.limit,
                cohort=body.cohort,
                delay_s=body.delay,
                dry_run=body.dry_run,
                force=body.force,
            )
        return enqueue_linkedin_find_durable(
            cohort=body.cohort,
            limit=body.limit,
            delay_s=body.delay,
            dry_run=False,
            force=body.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
