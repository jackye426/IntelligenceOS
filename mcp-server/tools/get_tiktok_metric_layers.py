"""MCP tools for TikTok velocity (Display snapshots) and Studio quality metrics."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from tools.tiktok_metrics_layers import (
    compute_velocity,
    fetch_account_daily,
    fetch_latest_studio_insight,
    fetch_metric_snapshots,
)


def get_tiktok_metric_velocity(video_id: str, hours: int = 48) -> dict[str, Any]:
    summary = f"video_id={video_id} hours={hours}"
    try:
        snapshots = fetch_metric_snapshots(video_id, hours=hours)
        velocity = compute_velocity(snapshots)
        result = {
            "video_id": video_id,
            "hours": hours,
            "velocity": velocity,
            "snapshots": snapshots,
            "snapshot_count": len(snapshots),
        }
        log_tool_call(
            tool_name="get_tiktok_metric_velocity",
            request_summary=summary,
            success=True,
            entity_type="content_post",
            entity_id=video_id,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_tiktok_metric_velocity",
            request_summary=summary,
            success=False,
            entity_type="content_post",
            entity_id=video_id,
            error=str(exc),
        )
        raise


def get_tiktok_studio_insight(video_id: str) -> dict[str, Any]:
    summary = f"video_id={video_id}"
    try:
        row = fetch_latest_studio_insight(video_id)
        if not row:
            result = {"found": False, "video_id": video_id}
        else:
            result = {
                "found": True,
                "video_id": video_id,
                "captured_at": row.get("captured_at"),
                "metrics": row.get("metrics") or {},
            }
        log_tool_call(
            tool_name="get_tiktok_studio_insight",
            request_summary=summary,
            success=True,
            entity_type="content_post",
            entity_id=video_id,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_tiktok_studio_insight",
            request_summary=summary,
            success=False,
            entity_type="content_post",
            entity_id=video_id,
            error=str(exc),
        )
        raise


def get_tiktok_account_daily(since: str | None = None, limit: int = 90) -> dict[str, Any]:
    summary = f"since={since} limit={limit}"
    try:
        rows = fetch_account_daily(since=since, limit=limit)
        result = {"count": len(rows), "days": rows}
        log_tool_call(
            tool_name="get_tiktok_account_daily",
            request_summary=summary,
            success=True,
            entity_type="tiktok_account_daily",
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_tiktok_account_daily",
            request_summary=summary,
            success=False,
            entity_type="tiktok_account_daily",
            error=str(exc),
        )
        raise
