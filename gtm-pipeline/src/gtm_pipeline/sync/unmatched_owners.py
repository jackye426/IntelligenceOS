"""Upsert gtm_unmatched_owners on practitioner_id (keep email)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from gtm_pipeline.shared.supabase_client import get_client

logger = logging.getLogger(__name__)


def upsert_unmatched_owner(row: dict[str, Any]) -> dict[str, Any]:
    """Never drop an owner-first hit — upsert by practitioner_id, preserve email."""
    client = get_client()
    practitioner_id = row["practitioner_id"]
    payload = {
        **row,
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }

    existing = (
        client.table("gtm_unmatched_owners")
        .select("id, email")
        .eq("practitioner_id", practitioner_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        # Keep prior email if new payload somehow blanks it
        if not payload.get("email") and existing[0].get("email"):
            payload["email"] = existing[0]["email"]
        updated = (
            client.table("gtm_unmatched_owners")
            .update(payload)
            .eq("id", existing[0]["id"])
            .execute()
            .data
            or []
        )
        logger.info("Updated unmatched owner %s", practitioner_id)
        return updated[0] if updated else payload

    inserted = client.table("gtm_unmatched_owners").insert(payload).execute().data or []
    logger.info("Inserted unmatched owner %s", practitioner_id)
    return inserted[0] if inserted else payload
