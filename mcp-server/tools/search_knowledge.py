"""Semantic knowledge search over document_embeddings."""

from __future__ import annotations

from typing import Any

from common import config
from common.audit import log_tool_call
from common.openrouter_client import embed_text
from common.supabase_client import get_client


def _missing_scoped_function(exc: Exception) -> bool:
    """True when PostgREST cannot resolve the scoped match_documents.

    PGRST202 = no function with that argument list. PGRST203 = several
    candidates and none preferred, which is what the pre-013 overloads produce.
    """
    text = str(exc)
    return (
        "PGRST202" in text
        or "PGRST203" in text
        or "filter_owner_scope" in text
        or "Could not find the function" in text
        or "Could not choose the best candidate" in text
    )


def search_knowledge(
    query: str,
    entity_type: str | None = None,
    match_count: int = 5,
) -> list[dict[str, Any]]:
    summary = f"query={query!r}, entity_type={entity_type}, match_count={match_count}"
    try:
        vector = embed_text(query)
        try:
            result = get_client().rpc(
                "match_documents",
                {
                    "query_embedding": vector,
                    "match_count": match_count,
                    "filter_type": entity_type,
                    "max_sensitivity": config.MCP_MAX_SENSITIVITY,
                    "filter_owner_scope": "docmap",
                },
            ).execute()
        except Exception as exc:  # noqa: BLE001
            # There is deliberately NO fallback to an older overload. The 3-arg
            # version predates owner_scope and filters nothing, so retrying
            # against it would silently serve peer-library chunks into DocMap
            # answers — the exact leak this scoping exists to prevent. Fail with
            # an actionable message instead.
            if _missing_scoped_function(exc):
                raise RuntimeError(
                    "match_documents(filter_owner_scope) is missing from the database, "
                    "so scoped semantic search cannot run. Apply "
                    "sql/013a_match_documents.sql in the Supabase SQL editor, then "
                    "verify with scripts/verify-supabase-schema.py. Retrieval is "
                    "disabled rather than falling back to an unscoped function."
                ) from exc
            raise

        rows = [
            {
                "snippet": row.get("content"),
                "source_title": row.get("source_title"),
                "source_url": row.get("source_url"),
                "entity_type": row.get("entity_type"),
                "entity_id": row.get("entity_id"),
                "chunk_index": row.get("chunk_index"),
                "sensitivity": row.get("sensitivity"),
                "similarity": round(float(row.get("similarity", 0)), 4),
                "metadata": row.get("metadata") or {},
            }
            for row in result.data or []
        ]
        log_tool_call(tool_name="search_knowledge", request_summary=summary, success=True)
        return rows
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="search_knowledge",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise
