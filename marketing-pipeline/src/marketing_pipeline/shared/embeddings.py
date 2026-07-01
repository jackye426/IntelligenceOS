"""Citation-aware embedding upserts with content-hash skip."""

from __future__ import annotations

from typing import Any

from marketing_pipeline.shared.chunking import chunk_text
from marketing_pipeline.shared.hashing import content_hash
from marketing_pipeline.shared.openrouter_client import embed_text
from marketing_pipeline.shared.supabase_client import get_client


def _existing_hashes(entity_type: str, entity_id: str) -> dict[int, str]:
    client = get_client()
    rows = (
        client.table("document_embeddings")
        .select("chunk_index, content_hash")
        .eq("entity_type", entity_type)
        .eq("entity_id", entity_id)
        .execute()
        .data
        or []
    )
    return {int(r["chunk_index"]): r["content_hash"] for r in rows if r.get("content_hash")}


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
    skip_unchanged: bool = True,
) -> int:
    chunks = chunk_text(text)
    if not chunks:
        return 0

    client = get_client()
    prior = _existing_hashes(entity_type, entity_id) if skip_unchanged else {}
    written = 0

    for index, chunk in enumerate(chunks):
        digest = content_hash(chunk)
        if skip_unchanged and prior.get(index) == digest:
            continue

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
            "content_hash": digest,
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


def delete_embeddings_for_entity(entity_type: str, entity_id: str) -> None:
    client = get_client()
    client.table("document_embeddings").delete().eq("entity_type", entity_type).eq(
        "entity_id", entity_id
    ).execute()


def delete_orphan_tiktok_embeddings(
    *,
    post_ids: set[str],
    comment_entity_ids: set[str],
    video_ids: set[str],
) -> int:
    client = get_client()
    removed = 0
    rows = (
        client.table("document_embeddings")
        .select("id, entity_type, entity_id, metadata")
        .in_("entity_type", ["content_post", "tiktok_transcript", "tiktok_comment_batch"])
        .execute()
        .data
        or []
    )
    for row in rows:
        et = row.get("entity_type")
        eid = row.get("entity_id")
        meta = row.get("metadata") or {}
        stale = False
        if et in ("content_post", "tiktok_transcript"):
            stale = eid not in post_ids
        elif et == "tiktok_comment_batch":
            stale = eid not in comment_entity_ids and str(meta.get("video_id")) not in video_ids
        if stale:
            client.table("document_embeddings").delete().eq("id", row["id"]).execute()
            removed += 1
    return removed
