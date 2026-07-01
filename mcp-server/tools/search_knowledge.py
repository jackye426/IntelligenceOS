"""Semantic knowledge search over document_embeddings."""

from __future__ import annotations

from typing import Any

from common import config
from common.audit import log_tool_call
from common.openrouter_client import embed_text
from common.supabase_client import get_client


def search_knowledge(
    query: str,
    entity_type: str | None = None,
    match_count: int = 5,
) -> list[dict[str, Any]]:
    summary = f"query={query!r}, entity_type={entity_type}, match_count={match_count}"
    try:
        vector = embed_text(query)
        result = get_client().rpc(
            "match_documents",
            {
                "query_embedding": vector,
                "match_count": match_count,
                "filter_type": entity_type,
                "max_sensitivity": config.MCP_MAX_SENSITIVITY,
            },
        ).execute()

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
