"""Normalize and store TikTok Studio /aweme/v2/data/insight/ payloads."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from marketing_pipeline.shared.ingestion_log import finish_run, start_run
from marketing_pipeline.shared.supabase_client import get_client

logger = logging.getLogger(__name__)

JOB_NAME = "tiktok_studio_insight"


def _status_value(node: Any) -> Any:
    """Unwrap {status, value} Studio insight nodes."""
    if not isinstance(node, dict):
        return node
    if "value" in node and "status" in node:
        return node.get("value")
    return node


def normalize_insight_payload(
    payload: dict[str, Any],
    *,
    platform_post_id: str | None = None,
) -> dict[str, Any]:
    """Extract stable quality/distribution fields from an insight response."""
    video_info = payload.get("video_info") or {}
    stats = video_info.get("statistics") or {}
    aweme_id = (
        platform_post_id
        or video_info.get("aweme_id")
        or (stats and None)
    )
    if not aweme_id:
        # try nested
        aweme_id = str(video_info.get("aweme_id") or "")

    finish = _status_value((payload.get("video_finish_rate_realtime") or {}).get("value"))
    if isinstance(finish, dict):
        finish = finish.get("value")

    avg_watch = _status_value((payload.get("video_per_duration_realtime") or {}).get("value"))
    if isinstance(avg_watch, dict):
        avg_watch = avg_watch.get("value")

    total_watch = _status_value((payload.get("video_total_duration_realtime") or {}).get("value"))
    if isinstance(total_watch, dict):
        total_watch = total_watch.get("value")

    views = _status_value((payload.get("realtime_total_video_views") or {}).get("value"))
    if isinstance(views, dict):
        views = views.get("value")

    new_followers = _status_value((payload.get("realtime_new_followers") or {}).get("value"))
    if isinstance(new_followers, dict):
        new_followers = new_followers.get("value")

    traffic_raw = _status_value((payload.get("video_traffic_source_percent_realtime") or {}).get("value"))
    traffic: dict[str, float] = {}
    if isinstance(traffic_raw, dict) and "value" in traffic_raw:
        traffic_raw = traffic_raw.get("value")
    if isinstance(traffic_raw, list):
        for item in traffic_raw:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "")
            try:
                traffic[key] = float(item.get("value") or 0)
            except (TypeError, ValueError):
                continue

    retention_node = payload.get("video_retention_rate_realtime") or {}
    retention_val = _status_value(retention_node.get("value"))
    retention_list: list[dict[str, Any]] = []
    if isinstance(retention_val, dict) and isinstance(retention_val.get("list"), list):
        retention_list = retention_val["list"]
    elif isinstance(retention_val, list):
        retention_list = retention_val

    avg_watch_hist = payload.get("realtime_average_watch_time_history") or {}
    finish_hist = payload.get("realtime_finish_rate_history") or {}
    view_hist = payload.get("realtime_video_view_history") or {}

    duration_ms = (video_info.get("video") or {}).get("duration")

    return {
        "platform_post_id": str(aweme_id or platform_post_id or ""),
        "views": views,
        "avg_watch_sec": avg_watch,
        "total_watch_sec": total_watch,
        "finish_rate": finish,
        "new_followers_from_video": new_followers,
        "traffic_sources": traffic,
        "retention_curve": retention_list,
        "duration_ms": duration_ms,
        "public_stats": {
            "play_count": stats.get("play_count"),
            "digg_count": stats.get("digg_count"),
            "comment_count": stats.get("comment_count"),
            "share_count": stats.get("share_count"),
            "collect_count": stats.get("collect_count"),
        },
        "histories": {
            "avg_watch_total": avg_watch_hist.get("total"),
            "finish_rate_total": finish_hist.get("total"),
            "views_total": view_hist.get("total"),
        },
        "unique_viewer_num": _status_value(payload.get("unique_viewer_num")),
        "follower_num": _status_value(payload.get("follower_num")),
    }


def ingest_insight_json(
    path: Path,
    *,
    platform_post_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Ingest one Studio insight JSON file (from HAR export or Playwright capture)."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "log" in payload and "entries" in payload.get("log", {}):
        raise ValueError("Pass a single insight JSON response, not a full HAR file")

    metrics = normalize_insight_payload(payload, platform_post_id=platform_post_id)
    video_id = metrics.get("platform_post_id") or platform_post_id
    if not video_id:
        raise ValueError("platform_post_id missing; pass --video-id")

    run_id = start_run(JOB_NAME, {"path": str(path), "video_id": video_id, "dry_run": dry_run})
    try:
        client = get_client()
        content_rows = (
            client.table("content_posts")
            .select("id")
            .eq("platform", "tiktok")
            .eq("platform_post_id", video_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        content_post_id = content_rows[0]["id"] if content_rows else None
        captured_at = datetime.now(timezone.utc).isoformat()
        row = {
            "platform_post_id": video_id,
            "content_post_id": content_post_id,
            "captured_at": captured_at,
            "metrics": metrics,
            "raw": payload,
        }
        if not dry_run:
            client.table("tiktok_studio_insights").insert(row).execute()
        finish_run(
            run_id,
            "success",
            {"rows_seen": 1, "rows_inserted": 0 if dry_run else 1, "rows_updated": 0},
        )
        return {
            "video_id": video_id,
            "metrics": metrics,
            "dry_run": dry_run,
            "captured_at": captured_at,
        }
    except Exception as exc:
        finish_run(run_id, "failed", {}, error=str(exc))
        raise


def ingest_insight_dir(
    directory: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Ingest all *.json insight payloads in a directory (filename may be video_id.json)."""
    files = sorted(directory.glob("*.json"))
    results = []
    for path in files:
        vid = path.stem if path.stem.isdigit() else None
        results.append(ingest_insight_json(path, platform_post_id=vid, dry_run=dry_run))
    return {"count": len(results), "results": results}
