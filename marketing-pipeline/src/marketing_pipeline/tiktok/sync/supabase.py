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
from marketing_pipeline.tiktok.stages.build_strategy_brief import build_strategy_brief, write_strategy_brief
from marketing_pipeline.tiktok.stages.collect_catalog import load_catalog
from marketing_pipeline.tiktok.stages.extract_hooks import resolve_primary_hook
from marketing_pipeline.tiktok.stages.performance_tier import compute_performance_tiers
from marketing_pipeline.tiktok.stages.tiktok_insights_store import (
    STATE_PATH,
    STRATEGY_PLATFORM,
    STRATEGY_POST_ID,
    load_state,
)
from marketing_pipeline.tiktok.stages.video_components_store import load_components

JOB_NAME = "tiktok_marketing_sync"
STRATEGY_BRIEF_ENTITY = "tiktok_strategy_brief"
STRATEGY_BRIEF_ENTITY_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "tiktok-strategy-brief:v1"))


def load_dataset(path: Path | None = None) -> TikTokMarketingDataset:
    target = path or config.DATASET_JSON
    if not target.exists():
        raise FileNotFoundError(f"Dataset not found: {target}. Run: tiktok export")
    data = json.loads(target.read_text(encoding="utf-8"))
    return TikTokMarketingDataset.model_validate(data)


def _catalog_metrics(entry: dict[str, Any]) -> dict[str, Any]:
    def _int(key: str) -> int | None:
        raw = entry.get(key)
        if raw == "" or raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    views = _int("view_count") or 0
    saves = _int("save_count")
    metrics: dict[str, Any] = {
        "views": views,
        "likes": _int("like_count"),
        "comments": _int("comment_count"),
        "saves": saves,
        "shares": _int("share_count"),
        "duration_sec": _int("duration_sec"),
    }
    if views and saves is not None:
        metrics["saves_per_1k_views"] = round((saves / views) * 1000, 2)
    return metrics


def _catalog_stub_payload(video_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    caption = entry.get("description") or entry.get("title") or ""
    title = (caption.split("\n")[0].strip()[:200]) if caption else None
    synced_at = datetime.now(timezone.utc).isoformat()
    return {
        "platform": "tiktok",
        "platform_post_id": video_id,
        "title": title,
        "post_url": entry.get("url") or f"https://www.tiktok.com/@docmap/video/{video_id}",
        "posted_at": entry.get("post_datetime_utc") or entry.get("post_date_utc"),
        "topic": None,
        "format": "video",
        "hook": title,
        "caption": caption,
        "transcript": None,
        "metrics": _catalog_metrics(entry),
        "metadata": {
            "source": "marketing_pipeline",
            "is_catalog_stub": True,
            "transcript_status": "pending",
            "synced_at": synced_at,
            "dataset_version": config.DATASET_VERSION,
        },
    }


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
        "is_catalog_stub": False,
    }
    if record.comment_analysis:
        metadata["comment_analysis"] = record.comment_analysis.model_dump()
    if performance_tier:
        metadata["performance_tier"] = performance_tier

    components = load_components(video_id)
    if components:
        metadata["components"] = components.model_dump(mode="json")

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


def _merge_by_id(
    primary: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
    *,
    id_key: str,
) -> list[dict[str, Any]]:
    """Merge lists by id; primary wins on conflict, then append missing from secondary."""
    merged: dict[str, dict[str, Any]] = {}
    for item in secondary:
        key = str(item.get(id_key) or "")
        if key:
            merged[key] = item
    for item in primary:
        key = str(item.get(id_key) or "")
        if key:
            merged[key] = item
    return list(merged.values())


def _sync_strategy_state(*, brief: dict[str, Any], skip_embed: bool) -> int:
    client = get_client()
    state = load_state()
    existing = (
        client.table("content_posts")
        .select("id, metadata")
        .eq("platform", STRATEGY_PLATFORM)
        .eq("platform_post_id", STRATEGY_POST_ID)
        .limit(1)
        .execute()
    )
    existing_meta: dict[str, Any] = {}
    if existing.data:
        existing_meta = existing.data[0].get("metadata") or {}

    # Preserve MCP-written decisions/insights when local file is empty or partial
    local_decisions = list(state.get("decisions") or [])
    remote_decisions = list(existing_meta.get("decisions") or [])
    decisions = _merge_by_id(local_decisions, remote_decisions, id_key="decision_id")

    local_insights = list(state.get("insights") or [])
    remote_insights = list(existing_meta.get("insights") or [])
    insights = _merge_by_id(local_insights, remote_insights, id_key="insight_id")

    open_statuses = {"proposed", "committed", "done"}
    open_decisions = [d for d in decisions if d.get("status") in open_statuses]
    closed_decisions = [
        d for d in decisions if d.get("status") in {"outcome_recorded", "cancelled"}
    ]
    closed_decisions.sort(
        key=lambda d: d.get("closed_at") or d.get("created_at") or "",
        reverse=True,
    )
    brief = dict(brief)
    brief["7_decisions"] = {
        "open": open_decisions[:15],
        "recent_closed": closed_decisions[:10],
        "open_count": len(open_decisions),
        "closed_count": len(closed_decisions),
    }

    payload = {
        "platform": STRATEGY_PLATFORM,
        "platform_post_id": STRATEGY_POST_ID,
        "title": "TikTok strategy state",
        "post_url": None,
        "posted_at": datetime.now(timezone.utc).isoformat(),
        "topic": "strategy",
        "format": "metadata",
        "hook": None,
        "caption": None,
        "transcript": None,
        "metrics": {},
        "metadata": {
            "source": "marketing_pipeline",
            "strategy_brief": brief,
            "insights": insights,
            "decisions": decisions,
            "changelog": state.get("changelog") or existing_meta.get("changelog") or [],
            "approved_patterns": state.get("approved_patterns")
            or existing_meta.get("approved_patterns")
            or [],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    if existing.data:
        client.table("content_posts").update(payload).eq("id", existing.data[0]["id"]).execute()
    else:
        client.table("content_posts").insert(payload).execute()

    if skip_embed:
        return 0

    text_parts = [
        brief.get("1_constitution") or "",
        "\n".join(brief.get("6_changelog") or []),
        json.dumps(brief.get("3_approved_insights") or [], ensure_ascii=False)[:8000],
        json.dumps(brief.get("7_decisions") or {}, ensure_ascii=False)[:4000],
    ]
    body = "\n\n".join(p for p in text_parts if p.strip())
    return upsert_embedding_chunks(
        entity_type="marketing_playbook",
        entity_id=STRATEGY_BRIEF_ENTITY_ID,
        text=body,
        source_table="marketing_playbooks",
        source_title="tiktok-strategy-brief",
        source_url=None,
        metadata={"slug": "tiktok-strategy-brief", "status": "approved"},
    )


def _prune_stale_tiktok(canonical_ids: set[str]) -> int:
    client = get_client()
    rows = (
        client.table("content_posts")
        .select("id, platform_post_id, metadata")
        .eq("platform", "tiktok")
        .execute()
        .data
        or []
    )
    removed = 0
    for row in rows:
        pid = str(row.get("platform_post_id") or "")
        if pid in canonical_ids:
            continue
        meta = row.get("metadata") or {}
        if meta.get("is_catalog_stub"):
            continue
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
    catalog = load_catalog(config.CATALOG_DIR)
    canonical_ids = set(dataset.videos.keys())
    stub_ids = {vid for vid in catalog if vid not in dataset.videos}
    canonical_ids |= stub_ids

    if dry_run:
        return {
            "rows_seen": len(canonical_ids),
            "rows_inserted": 0,
            "rows_updated": 0,
            "rows_pruned": 0,
            "embeddings_written": 0,
            "catalog_stubs": len(stub_ids),
        }

    run_id = start_run(JOB_NAME, {"dataset": str(dataset_path or config.DATASET_JSON)})
    counts = {
        "rows_seen": 0,
        "rows_inserted": 0,
        "rows_updated": 0,
        "rows_pruned": 0,
        "embeddings_written": 0,
        "catalog_stubs": 0,
    }

    post_ids: set[str] = set()
    comment_entity_ids: set[str] = set()

    try:
        write_strategy_brief(dataset)
        brief = build_strategy_brief(dataset)
        counts["embeddings_written"] += _sync_strategy_state(brief=brief, skip_embed=skip_embed)

        counts["rows_seen"] = len(canonical_ids)
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

        for video_id in stub_ids:
            entry = catalog[video_id]
            payload = _catalog_stub_payload(video_id, entry)
            post_id, inserted, embeds = _upsert_post(payload, skip_embed=skip_embed)
            post_ids.add(post_id)
            counts["catalog_stubs"] += 1
            if inserted:
                counts["rows_inserted"] += 1
            else:
                counts["rows_updated"] += 1
            counts["embeddings_written"] += embeds

        counts["rows_pruned"] = _prune_stale_tiktok(canonical_ids)
        counts["embeddings_pruned"] = delete_orphan_tiktok_embeddings(
            post_ids=post_ids,
            comment_entity_ids=comment_entity_ids,
            video_ids=set(dataset.videos.keys()),
        )

        finish_run(run_id, "success", counts)
        return counts
    except Exception as exc:  # noqa: BLE001
        finish_run(run_id, "failed", counts, error=str(exc))
        raise
