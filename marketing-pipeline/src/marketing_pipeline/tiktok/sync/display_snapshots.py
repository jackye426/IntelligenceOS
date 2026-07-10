"""Write Display API metric snapshots to Supabase."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from marketing_pipeline.shared.ingestion_log import finish_run, start_run
from marketing_pipeline.shared.supabase_client import get_client
from marketing_pipeline.tiktok.stages.display_api import (
    DisplayApiNotConfigured,
    iter_all_videos,
    metrics_from_display_video,
    query_videos,
)

logger = logging.getLogger(__name__)

JOB_NAME = "tiktok_display_snapshots"
SOURCE = "display_api"


def _resolve_content_post_ids(video_ids: list[str]) -> dict[str, str]:
    if not video_ids:
        return {}
    client = get_client()
    mapping: dict[str, str] = {}
    # PostgREST .in_ chunks
    for i in range(0, len(video_ids), 100):
        chunk = video_ids[i : i + 100]
        rows = (
            client.table("content_posts")
            .select("id, platform_post_id")
            .eq("platform", "tiktok")
            .in_("platform_post_id", chunk)
            .execute()
            .data
            or []
        )
        for row in rows:
            mapping[row["platform_post_id"]] = row["id"]
    return mapping


def _merge_latest_into_content_posts(
    videos: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> int:
    """Update public counters on content_posts without wiping saves."""
    client = get_client()
    updated = 0
    for video in videos:
        video_id = str(video.get("id") or "")
        if not video_id:
            continue
        metrics = metrics_from_display_video(video)
        existing = (
            client.table("content_posts")
            .select("id, metrics")
            .eq("platform", "tiktok")
            .eq("platform_post_id", video_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not existing:
            continue
        row = existing[0]
        merged = dict(row.get("metrics") or {})
        for key in ("views", "likes", "comments", "shares", "duration_sec"):
            if metrics.get(key) is not None:
                merged[key] = metrics[key]
        # Preserve saves / per-1k from yt-dlp pipeline
        views = merged.get("views") or 0
        saves = merged.get("saves")
        if views and saves is not None:
            try:
                merged["saves_per_1k_views"] = round((int(saves) / int(views)) * 1000, 2)
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        if dry_run:
            updated += 1
            continue
        client.table("content_posts").update({"metrics": merged}).eq("id", row["id"]).execute()
        updated += 1
    return updated


def run_display_snapshots(
    *,
    video_ids: list[str] | None = None,
    update_latest: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fetch Display API videos and append snapshot rows."""
    run_id = start_run(JOB_NAME, {"dry_run": dry_run, "video_ids": bool(video_ids)})
    try:
        if video_ids:
            videos = query_videos(video_ids)
        else:
            videos = iter_all_videos()

        captured_at = datetime.now(timezone.utc).isoformat()
        ids = [str(v.get("id")) for v in videos if v.get("id")]
        id_map = _resolve_content_post_ids(ids)

        rows: list[dict[str, Any]] = []
        for video in videos:
            video_id = str(video.get("id") or "")
            if not video_id:
                continue
            rows.append(
                {
                    "platform": "tiktok",
                    "platform_post_id": video_id,
                    "content_post_id": id_map.get(video_id),
                    "source": SOURCE,
                    "captured_at": captured_at,
                    "metrics": metrics_from_display_video(video),
                    "raw": {
                        "id": video.get("id"),
                        "create_time": video.get("create_time"),
                        "title": video.get("title"),
                        "view_count": video.get("view_count"),
                        "like_count": video.get("like_count"),
                        "comment_count": video.get("comment_count"),
                        "share_count": video.get("share_count"),
                        "duration": video.get("duration"),
                    },
                }
            )

        inserted = 0
        if rows and not dry_run:
            client = get_client()
            # Insert in chunks
            for i in range(0, len(rows), 100):
                chunk = rows[i : i + 100]
                client.table("content_metric_snapshots").insert(chunk).execute()
                inserted += len(chunk)
        elif dry_run:
            inserted = len(rows)

        latest_updated = 0
        if update_latest and videos:
            latest_updated = _merge_latest_into_content_posts(videos, dry_run=dry_run)

        counts = {
            "rows_seen": len(videos),
            "rows_inserted": inserted,
            "rows_updated": latest_updated,
        }
        finish_run(run_id, "success", counts)
        return {**counts, "captured_at": captured_at, "dry_run": dry_run}
    except DisplayApiNotConfigured as exc:
        finish_run(run_id, "failed", {}, error=str(exc))
        raise
    except Exception as exc:
        finish_run(run_id, "failed", {}, error=str(exc))
        raise
