"""Embed playbook markdown into document_embeddings (MCP-native, no CLI)."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from common.openrouter_client import embed_text
from common.supabase_client import get_client

PLAYBOOK_ENTITY = "marketing_playbook"


def _chunk_text(text: str, max_chars: int = 2500, overlap: int = 250) -> list[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + max_chars, len(cleaned))
        chunks.append(cleaned[start:end])
        if end >= len(cleaned):
            break
        start = max(0, end - overlap)
    return chunks


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _entity_id(slug: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"playbook:{slug}"))


def sync_playbook_content(
    *,
    filename: str,
    content: str,
    slug: str | None = None,
) -> dict[str, Any]:
    """Upsert embedding chunks for one playbook file. Returns counts."""
    slug = slug or filename
    entity_id = _entity_id(slug)
    chunks = _chunk_text(content)
    if not chunks:
        return {"ok": False, "error": "empty content", "chunks_written": 0}

    client = get_client()
    prior_rows = (
        client.table("document_embeddings")
        .select("chunk_index, content_hash")
        .eq("entity_type", PLAYBOOK_ENTITY)
        .eq("entity_id", entity_id)
        .execute()
        .data
        or []
    )
    prior = {int(r["chunk_index"]): r["content_hash"] for r in prior_rows if r.get("content_hash")}

    written = 0
    for index, chunk in enumerate(chunks):
        digest = _content_hash(chunk)
        if prior.get(index) == digest:
            continue
        vector = embed_text(chunk)
        client.table("document_embeddings").upsert(
            {
                "entity_type": PLAYBOOK_ENTITY,
                "entity_id": entity_id,
                "content": chunk,
                "embedding": vector,
                "source_table": "marketing_playbooks",
                "source_title": filename,
                "source_url": None,
                "chunk_index": index,
                "content_hash": digest,
                "sensitivity": "internal",
                "owner_scope": "docmap",
                "metadata": {"slug": slug, "status": "approved", "source": "mcp_constitution"},
            },
            on_conflict="entity_type,entity_id,chunk_index",
        ).execute()
        written += 1

    return {"ok": True, "entity_id": entity_id, "chunks_written": written, "slug": slug}
