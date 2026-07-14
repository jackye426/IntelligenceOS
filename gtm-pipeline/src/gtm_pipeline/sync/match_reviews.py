"""Upsert ambiguous matches into gtm_match_reviews."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from gtm_pipeline import config
from gtm_pipeline.shared.supabase_client import get_client, supabase_configured

logger = logging.getLogger(__name__)


def maybe_queue_match_review(
    *,
    entity_type: str,
    candidate: dict[str, Any],
    target: dict[str, Any],
    confidence: float,
    reasons: list[str],
    provenance: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any] | None:
    """Queue for review when confidence is in [review_threshold, auto_accept)."""
    if confidence >= config.MATCH_AUTO_ACCEPT:
        return None
    if confidence < config.MATCH_REVIEW_THRESHOLD:
        return None

    payload = {
        "entity_type": entity_type,
        "candidate": candidate,
        "target": target,
        "confidence": confidence,
        "reasons": reasons,
        "status": "pending",
        "provenance": provenance or {},
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    if dry_run or not supabase_configured():
        logger.info("[dry-run] would queue match review conf=%.3f type=%s", confidence, entity_type)
        return payload

    client = get_client()
    inserted = client.table("gtm_match_reviews").insert(payload).execute().data or []
    return inserted[0] if inserted else payload
