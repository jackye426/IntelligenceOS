"""HTTP service for GTM Account Intelligence scrapes (Railway).

Local:
  uvicorn gtm_pipeline.service:app --reload --port 8080

Auth: set GTM_SERVICE_TOKEN (or reuse MCP_AUTH_TOKEN). Send
  Authorization: Bearer <token>
on mutating endpoints. /health is open.
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from gtm_pipeline import config

logger = logging.getLogger("gtm_pipeline.service")

app = FastAPI(title="GTM Pipeline", version="0.1.0")


def _expected_token() -> str:
    return (
        os.getenv("GTM_SERVICE_TOKEN")
        or os.getenv("MCP_AUTH_TOKEN")
        or ""
    ).strip()


async def require_auth(authorization: str | None = Header(default=None)) -> None:
    expected = _expected_token()
    if not expected:
        # Fail closed in production when a public domain is present.
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


class DoctifyExtractBody(BaseModel):
    url: str = Field(default=config.DOCTIFY_FIXTURE_URL)
    upsert: bool = True
    dry_run: bool = False


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


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "gtm-pipeline",
        "supabase_configured": bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_ROLE_KEY),
        "auth_configured": bool(_expected_token()),
    }


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


@app.post("/owners/scan", dependencies=[Depends(require_auth)])
def owners_scan(body: OwnersScanBody) -> dict[str, Any]:
    from gtm_pipeline.owner_discovery import discover_owners

    logger.info("owners scan limit=%s dry_run=%s", body.limit, body.dry_run)
    return discover_owners(dry_run=body.dry_run, limit=body.limit)


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
