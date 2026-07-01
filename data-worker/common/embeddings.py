"""Upsert citation-aware embedding chunks."""

from __future__ import annotations

from typing import Any

from .chunking import chunk_text
from .hashing import content_hash
from .openrouter_client import embed_text
from .supabase_client import get_client


def upsert_embedding_chunks(
    *,
    entity_type: str,
    entity_id: str,
    text: str,
    source_table: str,
    source_title: str | None,
    source_url: str | None,
    sensitivity: str = "internal",
    metadata: dict[str, Any] | None = None,
) -> int:
    chunks = chunk_text(text)
    if not chunks:
        return 0

    client = get_client()
    written = 0

    for index, chunk in enumerate(chunks):
        vector = embed_text(chunk)
        row = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "content": chunk,
            "embedding": vector,
            "source_table": source_table,
            "source_title": source_title,
            "source_url": source_url,
            "chunk_index": index,
            "content_hash": content_hash(chunk),
            "sensitivity": sensitivity,
            "owner_scope": "docmap",
            "metadata": metadata or {},
        }
        client.table("document_embeddings").upsert(
            row,
            on_conflict="entity_type,entity_id,chunk_index",
        ).execute()
        written += 1

    return written
