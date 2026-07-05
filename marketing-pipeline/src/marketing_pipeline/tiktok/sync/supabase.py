"""Sync tiktok_marketing_dataset.json to Supabase."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from marketing_pipeline import config
from marketing_pipeline.shared.embeddings import (
    delete_orphan_tiktok_embeddings,
    upsert_embedding_chunks,
)
from marketing_pipeline.shared.ingestion_log import finish_run, start_run
from marketing_pipeline.shared.supabase_client import get_client
from marketing_pipeline.tiktok.models import TikTokMarketingDataset, TikTokVideoRecord
from marketing_pipeline.tiktok.stages.extract_hooks import resolve_primary_hook
from marketing_pipeline.tiktok.stages.performance_tier import compute_performance_tiers

JOB_NAME = "tiktok_marketing_sync"


def load_dataset(path: Path | None = None) -> TikTokMarketingDataset:
    target = path or config.DATASET_JSON
    if not target.exists():
        raise FileNotFoundError(f"Dataset not found: {target}. Run: tiktok export")
    data = json.loads(target.read_text(encoding="utf-8"))
    return TikTokMarketingDataset.model_validate(data)


def _post_payload(
    video_id: str,
    record: TikTokVideoRecord,
    *,
    performance_tier: dict[str, Any] | None = None,
) -> dict[str, Any]:
    post = record.post
    hook = record.hook
    primary_hook = resolve_primary_hook(hook)
    title = None
    if post.caption:
        title = post.caption.split("\n")[0].strip()[:200]
    if not title and primary_hook:
        title = primary_hook[:200]

    topic = None
    if record.comment_analysis:
        topic = record.comment_analysis.primary_theme

    synced_at = datetime.now(timezone.utc).isoformat()
    metadata: dict[str, Any] = {
        "source": "marketing_pipeline",
        "dataset_version": config.DATASET_VERSION,
        "synced_at": synced_at,
        "format_guess": post.format_guess,
        "hook_detail": hook.model_dump(),
        "transcript_status": record.transcript.status,
        "whisper_model": record.transcript.model,
        "ab_pairs": record.ab_pairs,
    }
    if record.comment_analysis:
        metadata["comment_analysis"] = record.comment_analysis.model_dump()
    if performance_tier:
        metadata["performance_tier"] = performance_tier

    return {
        "platform": "tiktok",
        "platform_post_id": video_id,
        "title": title,
        "post_url": post.url,
        "posted_at": post.posted_at,
        "topic": topic,
        "format": post.format_guess or "video",
        "hook": primary_hook,
        "caption": post.caption,
        "transcript": record.transcript.full_text,
        "metrics": post.metrics.model_dump(exclude_none=True),
        "metadata": metadata,
    }


def _upsert_post(payload: dict[str, Any], *, skip_embed: bool) -> tuple[str, bool, int]:
    client = get_client()
    platform_post_id = payload["platform_post_id"]
    embeds_written = 0

    existing = (
        client.table("content_posts")
        .select("id")
        .eq("platform", "tiktok")
        .eq("platform_post_id", platform_post_id)
        .limit(1)
        .execute()
    )

    if existing.data:
        post_id = existing.data[0]["id"]
        client.table("content_posts").update(payload).eq("id", post_id).execute()
        inserted = False
    else:
        post_id = client.table("content_posts").insert(payload).execute().data[0]["id"]
        inserted = True

    if skip_embed:
        return post_id, inserted, embeds_written

    embedding_text = "\n\n".join(
        part
        for part in [
            f"Hook: {payload['hook']}" if payload.get("hook") else None,
            f"Caption: {payload['caption']}" if payload.get("caption") else None,
            f"Transcript: {payload['transcript']}" if payload.get("transcript") else None,
        ]
        if part
    )
    meta = {"platform": "tiktok", "video_id": platform_post_id, "source": "marketing_pipeline"}

    if embedding_text:
        embeds_written += upsert_embedding_chunks(
            entity_type="content_post",
            entity_id=post_id,
            text=embedding_text,
            source_table="content_posts",
            source_title=payload.get("title"),
            source_url=payload.get("post_url"),
            metadata=meta,
        )

    if payload.get("transcript"):
        embeds_written += upsert_embedding_chunks(
            entity_type="tiktok_transcript",
            entity_id=post_id,
            text=payload["transcript"],
            source_table="content_posts",
            source_title=payload.get("title"),
            source_url=payload.get("post_url"),
            metadata=meta,
        )

    return post_id, inserted, embeds_written


def _ingest_comment_batch(
    video_id: str,
    record: TikTokVideoRecord,
    *,
    skip_embed: bool,
) -> int:
    if skip_embed or not record.comments:
        return 0

    lines = []
    for comment in record.comments[:40]:
        themes = ", ".join(comment.themes) if comment.themes else "unlabeled"
        lines.append(f"- [{themes}] {comment.text}")

    if not lines:
        return 0

    batch_text = f"TikTok comment themes for video {video_id}:\n" + "\n".join(lines)
    entity_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"tiktok-comments:{video_id}"))

    return upsert_embedding_chunks(
        entity_type="tiktok_comment_batch",
        entity_id=entity_id,
        text=batch_text,
        source_table="content_posts",
        source_title=f"TikTok comments {video_id}",
        source_url=f"https://www.tiktok.com/@docmap/video/{video_id}",
        metadata={"platform": "tiktok", "video_id": video_id, "source": "marketing_pipeline"},
    )


def _prune_stale_tiktok(canonical_ids: set[str]) -> int:
    client = get_client()
    rows = (
        client.table("content_posts")
        .select("id, platform_post_id")
        .eq("platform", "tiktok")
        .execute()
        .data
        or []
    )
    removed = 0
    for row in rows:
        if row.get("platform_post_id") not in canonical_ids:
            client.table("content_posts").delete().eq("id", row["id"]).execute()
            removed += 1
    return removed


def run_sync(
    *,
    dataset_path: Path | None = None,
    dry_run: bool = False,
    skip_embed: bool = False,
) -> dict[str, int]:
    dataset = load_dataset(dataset_path)
    canonical_ids = set(dataset.videos.keys())

    if dry_run:
        return {
            "rows_seen": len(canonical_ids),
            "rows_inserted": 0,
            "rows_updated": 0,
            "rows_pruned": 0,
            "embeddings_written": 0,
        }

    run_id = start_run(JOB_NAME, {"dataset": str(dataset_path or config.DATASET_JSON)})
    counts = {
        "rows_seen": 0,
        "rows_inserted": 0,
        "rows_updated": 0,
        "rows_pruned": 0,
        "embeddings_written": 0,
    }

    post_ids: set[str] = set()
    comment_entity_ids: set[str] = set()

    try:
        counts["rows_seen"] = len(dataset.videos)
        tiers = compute_performance_tiers(dataset)

        for video_id, record in dataset.videos.items():
            payload = _post_payload(
                video_id, record, performance_tier=tiers.get(video_id)
            )
            post_id, inserted, embeds = _upsert_post(payload, skip_embed=skip_embed)
            post_ids.add(post_id)
            if inserted:
                counts["rows_inserted"] += 1
            else:
                counts["rows_updated"] += 1
            counts["embeddings_written"] += embeds
            counts["embeddings_written"] += _ingest_comment_batch(
                video_id, record, skip_embed=skip_embed
            )
            if record.comments:
                comment_entity_ids.add(
                    str(uuid.uuid5(uuid.NAMESPACE_URL, f"tiktok-comments:{video_id}"))
                )

        counts["rows_pruned"] = _prune_stale_tiktok(canonical_ids)
        counts["embeddings_pruned"] = delete_orphan_tiktok_embeddings(
            post_ids=post_ids,
            comment_entity_ids=comment_entity_ids,
            video_ids=canonical_ids,
        )

        finish_run(run_id, "success", counts)
        return counts
    except Exception as exc:  # noqa: BLE001
        finish_run(run_id, "failed", counts, error=str(exc))
        raise
