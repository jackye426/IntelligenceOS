"""Sync instagram_marketing_dataset.json to Supabase."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from marketing_pipeline import config
from marketing_pipeline.instagram.models import InstagramMarketingDataset, InstagramPost
from marketing_pipeline.shared.embeddings import upsert_embedding_chunks
from marketing_pipeline.shared.ingestion_log import finish_run, start_run
from marketing_pipeline.shared.supabase_client import get_client

JOB_NAME = "instagram_marketing_sync"
STRATEGY_POST_ID = "instagram-strategy-state"
STRATEGY_BRIEF_ENTITY_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "instagram-strategy-brief:v1"))


def load_dataset(path: Path | None = None) -> InstagramMarketingDataset:
    target = path or config.INSTAGRAM_DATASET_JSON
    if not target.exists():
        raise FileNotFoundError(f"Dataset not found: {target}. Run: instagram export")
    return InstagramMarketingDataset.model_validate_json(target.read_text(encoding="utf-8"))


def _payload(post: InstagramPost) -> dict[str, Any]:
    return {
        "platform": "instagram",
        "platform_post_id": post.post_id,
        "title": post.title,
        "post_url": post.url,
        "posted_at": post.posted_at,
        "topic": post.topic,
        "format": post.format,
        "hook": post.components.cover_hook or post.components.caption_opening,
        "caption": post.caption,
        "transcript": post.transcript,
        "metrics": post.metrics.model_dump(exclude_none=True),
        "metadata": {
            "source": "marketing_pipeline",
            "dataset_version": "1",
            "shortcode": post.shortcode,
            "media_type": post.media_type,
            "media_url": post.media_url,
            "thumbnail_url": post.thumbnail_url,
            "child_media": post.child_media,
            "instagram_components": post.components.model_dump(exclude_none=True),
            "raw_source_layers": post.raw_metadata.get("source_layers", []),
            "content_tracker": post.raw_metadata.get("content_tracker"),
        },
    }


def _embedding_text(post: InstagramPost) -> str:
    parts = [
        f"Format: {post.format}",
        f"Topic: {post.topic}" if post.topic else None,
        f"Hook: {post.components.cover_hook}" if post.components.cover_hook else None,
        f"Caption opening: {post.components.caption_opening}"
        if post.components.caption_opening
        else None,
        f"Caption: {post.caption}" if post.caption else None,
        f"CTA: {post.components.cta}" if post.components.cta else None,
        f"Creative pattern: {post.components.creative_pattern}"
        if post.components.creative_pattern
        else None,
    ]
    return "\n\n".join(part for part in parts if part)


def _upsert_post(post: InstagramPost, *, skip_embed: bool) -> tuple[str, bool, int]:
    client = get_client()
    payload = _payload(post)
    existing = (
        client.table("content_posts")
        .select("id")
        .eq("platform", "instagram")
        .eq("platform_post_id", post.post_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        post_id = existing[0]["id"]
        client.table("content_posts").update(payload).eq("id", post_id).execute()
        inserted = False
    else:
        post_id = client.table("content_posts").insert(payload).execute().data[0]["id"]
        inserted = True

    embeds = 0
    if not skip_embed:
        text = _embedding_text(post)
        if text.strip():
            embeds += upsert_embedding_chunks(
                entity_type="content_post",
                entity_id=post_id,
                text=text,
                source_table="content_posts",
                source_title=post.title,
                source_url=post.url,
                sensitivity="public",
                metadata={
                    "platform": "instagram",
                    "post_id": post.post_id,
                    "format": post.format,
                    "source": "marketing_pipeline",
                },
            )
    return post_id, inserted, embeds


def _load_strategy_brief() -> dict[str, Any]:
    if not config.INSTAGRAM_STRATEGY_BRIEF_JSON.exists():
        return {}
    return json.loads(config.INSTAGRAM_STRATEGY_BRIEF_JSON.read_text(encoding="utf-8"))


def _sync_strategy_brief(*, skip_embed: bool) -> int:
    brief = _load_strategy_brief()
    if not brief:
        return 0
    client = get_client()
    payload = {
        "platform": "instagram",
        "platform_post_id": STRATEGY_POST_ID,
        "title": "Instagram strategy state",
        "post_url": None,
        "posted_at": (brief.get("0_meta") or {}).get("updated_at"),
        "topic": "strategy",
        "format": "metadata",
        "hook": None,
        "caption": None,
        "transcript": None,
        "metrics": {},
        "metadata": {
            "source": "marketing_pipeline",
            "strategy_brief": brief,
        },
    }
    existing = (
        client.table("content_posts")
        .select("id")
        .eq("platform", "instagram")
        .eq("platform_post_id", STRATEGY_POST_ID)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        client.table("content_posts").update(payload).eq("id", existing[0]["id"]).execute()
    else:
        client.table("content_posts").insert(payload).execute()

    if skip_embed:
        return 0
    body = json.dumps(brief, ensure_ascii=False)[:12000]
    return upsert_embedding_chunks(
        entity_type="marketing_playbook",
        entity_id=STRATEGY_BRIEF_ENTITY_ID,
        text=body,
        source_table="marketing_playbooks",
        source_title="instagram-strategy-brief",
        source_url=None,
        metadata={"slug": "instagram-strategy-brief", "status": "approved"},
    )


def run_sync(
    *,
    dataset_path: Path | None = None,
    dry_run: bool = False,
    skip_embed: bool = False,
) -> dict[str, int]:
    dataset = load_dataset(dataset_path)
    counts = {
        "rows_seen": len(dataset.posts),
        "rows_inserted": 0,
        "rows_updated": 0,
        "embeddings_written": 0,
    }
    if dry_run:
        return counts

    run_id = start_run(JOB_NAME, {"dataset": str(dataset_path or config.INSTAGRAM_DATASET_JSON)})
    try:
        counts["embeddings_written"] += _sync_strategy_brief(skip_embed=skip_embed)
        for post in dataset.posts.values():
            _, inserted, embeds = _upsert_post(post, skip_embed=skip_embed)
            if inserted:
                counts["rows_inserted"] += 1
            else:
                counts["rows_updated"] += 1
            counts["embeddings_written"] += embeds
        finish_run(run_id, "success", counts)
        return counts
    except Exception as exc:  # noqa: BLE001
        finish_run(run_id, "failed", counts, error=str(exc))
        raise

