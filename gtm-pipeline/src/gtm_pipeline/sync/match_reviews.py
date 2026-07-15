"""Upsert ambiguous matches into gtm_match_reviews (flag for outreach review)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from gtm_pipeline import config
from gtm_pipeline.shared.supabase_client import get_client, supabase_configured

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def maybe_queue_match_review(
    *,
    entity_type: str,
    candidate: dict[str, Any],
    target: dict[str, Any],
    confidence: float,
    reasons: list[str],
    provenance: dict[str, Any] | None = None,
    clinic_intelligence_id: str | None = None,
    clinic_account_id: str | None = None,
    dedupe_key: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any] | None:
    """Queue for review when confidence is in [review_threshold, auto_accept).

    Does not auto-apply the match — outreach drafting should resolve pending rows.
    """
    if confidence >= config.MATCH_AUTO_ACCEPT:
        return None
    if confidence < config.MATCH_REVIEW_THRESHOLD:
        return None

    payload: dict[str, Any] = {
        "entity_type": entity_type,
        "candidate": candidate,
        "target": target,
        "confidence": confidence,
        "reasons": reasons,
        "status": "pending",
        "provenance": provenance or {},
        "clinic_intelligence_id": clinic_intelligence_id,
        "clinic_account_id": clinic_account_id,
        "updated_at": _now(),
    }
    if dedupe_key:
        payload["dedupe_key"] = dedupe_key

    if dry_run or not supabase_configured():
        logger.info(
            "[dry-run] would queue match review conf=%.3f type=%s key=%s",
            confidence,
            entity_type,
            dedupe_key,
        )
        return payload

    client = get_client()
    if dedupe_key:
        existing = (
            client.table("gtm_match_reviews")
            .select("id, status")
            .eq("dedupe_key", dedupe_key)
            .limit(1)
            .execute()
            .data
            or []
        )
        if existing:
            # Refresh pending; do not reopen approved/rejected
            if existing[0].get("status") == "pending":
                updated = (
                    client.table("gtm_match_reviews")
                    .update(payload)
                    .eq("id", existing[0]["id"])
                    .execute()
                    .data
                    or []
                )
                return updated[0] if updated else {**payload, "id": existing[0]["id"]}
            return existing[0]

    inserted = client.table("gtm_match_reviews").insert(payload).execute().data or []
    return inserted[0] if inserted else payload


def list_pending_reviews_for_clinic(
    *,
    clinic_intelligence_id: str | None = None,
    clinic_account_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if not supabase_configured():
        return []
    client = get_client()
    q = (
        client.table("gtm_match_reviews")
        .select("*")
        .eq("status", "pending")
        .order("confidence", desc=True)
        .limit(limit)
    )
    if clinic_intelligence_id:
        q = q.eq("clinic_intelligence_id", clinic_intelligence_id)
    elif clinic_account_id:
        q = q.eq("clinic_account_id", clinic_account_id)
    else:
        return []
    return q.execute().data or []
