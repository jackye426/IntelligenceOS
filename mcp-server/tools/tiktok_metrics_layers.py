"""MCP helpers for Display API velocity + Studio insight layers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from common.supabase_client import get_client


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_metric_snapshots(
    video_id: str,
    *,
    hours: int = 48,
    source: str = "display_api",
    limit: int = 200,
) -> list[dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        get_client()
        .table("content_metric_snapshots")
        .select("platform_post_id, source, captured_at, metrics")
        .eq("platform", "tiktok")
        .eq("platform_post_id", video_id)
        .eq("source", source)
        .gte("captured_at", since.isoformat())
        .order("captured_at", desc=False)
        .limit(limit)
        .execute()
        .data
        or []
    )
    return rows


def compute_velocity(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive views/hour (and likes/hour) from ordered snapshots."""
    if len(snapshots) < 2:
        return {
            "points": len(snapshots),
            "views_per_hour": None,
            "likes_per_hour": None,
            "delta_views": None,
            "elapsed_hours": None,
        }

    first, last = snapshots[0], snapshots[-1]
    t0 = _parse_ts(first.get("captured_at"))
    t1 = _parse_ts(last.get("captured_at"))
    m0 = first.get("metrics") or {}
    m1 = last.get("metrics") or {}
    if not t0 or not t1 or t1 <= t0:
        return {
            "points": len(snapshots),
            "views_per_hour": None,
            "likes_per_hour": None,
            "delta_views": None,
            "elapsed_hours": None,
        }

    hours = (t1 - t0).total_seconds() / 3600.0
    dv = int(m1.get("views") or 0) - int(m0.get("views") or 0)
    dl = int(m1.get("likes") or 0) - int(m0.get("likes") or 0)
    return {
        "points": len(snapshots),
        "from": first.get("captured_at"),
        "to": last.get("captured_at"),
        "delta_views": dv,
        "delta_likes": dl,
        "elapsed_hours": round(hours, 3),
        "views_per_hour": round(dv / hours, 2) if hours else None,
        "likes_per_hour": round(dl / hours, 2) if hours else None,
        "latest_views": m1.get("views"),
        "latest_likes": m1.get("likes"),
    }


def fetch_latest_studio_insight(video_id: str) -> dict[str, Any] | None:
    rows = (
        get_client()
        .table("tiktok_studio_insights")
        .select("platform_post_id, captured_at, metrics")
        .eq("platform_post_id", video_id)
        .order("captured_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def fetch_account_daily(*, since: str | None = None, limit: int = 90) -> list[dict[str, Any]]:
    q = (
        get_client()
        .table("tiktok_account_daily")
        .select(
            "day, video_views, profile_views, likes, comments, shares, account_handle, source"
        )
        .eq("account_handle", "docmap")
        .order("day", desc=True)
        .limit(limit)
    )
    if since:
        q = q.gte("day", since)
    return q.execute().data or []
