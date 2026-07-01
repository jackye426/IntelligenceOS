"""Practitioner search."""

from __future__ import annotations

from typing import Any

from common import config
from common.audit import log_tool_call
from common.supabase_client import get_client


SEARCH_COLUMNS = [
    "name",
    "email",
    "specialty",
    "title",
    "clinical_interests",
    "about",
    "research_interests",
    "nhs_base",
    "website",
]


def search_practitioners(
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    summary = f"query={query!r}, limit={limit}"
    try:
        client = get_client()
        table = config.PRACTITIONERS_TABLE
        term = query.strip()
        if not term:
            return []

        safe_limit = max(1, min(limit, 50))
        ilike = f"*{term.replace(',', ' ')}*"

        rows = (
            client.table(table)
            .select(
                "id, name, email, specialty, specialties, profile_urls, "
                "locations, website, clinical_interests, about"
            )
            .or_(
                ",".join(
                    f"{column}.ilike.{ilike}" for column in SEARCH_COLUMNS
                )
            )
            .limit(safe_limit)
            .execute()
            .data
            or []
        )

        result = [
            {
                "id": row.get("id"),
                "name": row.get("name"),
                "email": row.get("email"),
                "specialty": row.get("specialty"),
                "specialties": row.get("specialties"),
                "profile_urls": row.get("profile_urls"),
                "locations": row.get("locations"),
                "website": row.get("website"),
                "clinical_interests": row.get("clinical_interests"),
            }
            for row in rows
        ]
        log_tool_call(tool_name="search_practitioners", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="search_practitioners",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise
