"""Shared Instagram content_posts helpers for MCP tools."""

from __future__ import annotations

import statistics
from datetime import date, datetime, timezone
from typing import Any, Literal

from common.supabase_client import get_client

InstagramSortBy = Literal[
    "intent",
    "engagement",
    "engagement_per_1k",
    "saves_per_1k",
    "shares_per_1k",
    "comments_per_1k",
    "views",
    "likes",
    "posted_at",
]

INSTAGRAM_POST_COLUMNS = (
    "id, platform_post_id, title, post_url, posted_at, hook, caption, transcript, "
    "metrics, metadata, topic, format"
)


def fetch_instagram_posts(*, limit: int = 500) -> list[dict[str, Any]]:
    return (
        get_client()
        .table("content_posts")
        .select(INSTAGRAM_POST_COLUMNS)
        .eq("platform", "instagram")
        .neq("platform_post_id", "instagram-strategy-state")
        .order("posted_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )


def fetch_instagram_post(post_id: str) -> dict[str, Any] | None:
    rows = (
        get_client()
        .table("content_posts")
        .select(INSTAGRAM_POST_COLUMNS)
        .eq("platform", "instagram")
        .eq("platform_post_id", post_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def _metric(row: dict[str, Any], key: str) -> float:
    value = (row.get("metrics") or {}).get(key)
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def intent_score(row: dict[str, Any]) -> float:
    return (
        _metric(row, "follows") * 8
        + _metric(row, "profile_visits") * 4
        + _metric(row, "external_link_taps") * 6
        + _metric(row, "saves") * 2
        + _metric(row, "shares") * 2
        + _metric(row, "comments")
    )


def sort_score(row: dict[str, Any], sort_by: InstagramSortBy) -> float:
    metrics = row.get("metrics") or {}
    if sort_by == "intent":
        return intent_score(row)
    if sort_by == "engagement":
        return _metric(row, "engagement")
    if sort_by in {
        "engagement_per_1k",
        "saves_per_1k",
        "shares_per_1k",
        "comments_per_1k",
        "views",
        "likes",
    }:
        return float(metrics.get(sort_by) or 0)
    posted_at = row.get("posted_at")
    if not posted_at:
        return 0.0
    return float(str(posted_at).replace("Z", "+00:00")[:26].replace("T", "").replace(":", "").replace("-", "") or 0)


def rank_posts(rows: list[dict[str, Any]], sort_by: InstagramSortBy) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: sort_score(row, sort_by), reverse=True)


def filter_by_date(
    rows: list[dict[str, Any]],
    *,
    since: str | None = None,
    until: str | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        posted = str(row.get("posted_at") or "")[:10]
        if since and posted < since[:10]:
            continue
        if until and posted > until[:10]:
            continue
        out.append(row)
    return out


def cohort_medians(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {"intent": 0.0, "engagement": 0.0, "saves_per_1k": 0.0}
    return {
        "intent": statistics.median([intent_score(row) for row in rows]),
        "engagement": statistics.median([_metric(row, "engagement") for row in rows]),
        "saves_per_1k": statistics.median([_metric(row, "saves_per_1k") for row in rows]),
    }


def performance_tier(
    row: dict[str, Any],
    medians: dict[str, float],
    *,
    sort_by: InstagramSortBy,
) -> str:
    score = sort_score(row, sort_by)
    median = medians.get(sort_by if sort_by in medians else "intent", 0.0)
    if median <= 0:
        return "typical"
    ratio = score / median
    if ratio >= 1.25:
        return "outperform"
    if ratio <= 0.75:
        return "underperform"
    return "typical"


def post_summary(row: dict[str, Any], *, medians: dict[str, float] | None = None) -> dict[str, Any]:
    metrics = row.get("metrics") or {}
    meta = row.get("metadata") or {}
    components = meta.get("instagram_components") or {}
    summary: dict[str, Any] = {
        "post_id": row.get("platform_post_id"),
        "title": row.get("title"),
        "format": row.get("format"),
        "topic": row.get("topic"),
        "post_url": row.get("post_url"),
        "posted_at": row.get("posted_at"),
        "hook": row.get("hook"),
        "caption_opening": components.get("caption_opening"),
        "cta": components.get("cta"),
        "funnel_stage": components.get("funnel_stage"),
        "creative_pattern": components.get("creative_pattern"),
        "metrics": metrics,
        "intent_score": intent_score(row),
    }
    if medians is not None:
        summary["tier_vs_cohort_intent"] = performance_tier(row, medians, sort_by="intent")
        summary["tier_vs_cohort_saves_per_1k"] = performance_tier(
            row, medians, sort_by="saves_per_1k"
        )
    return summary


def library_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dates = [str(row.get("posted_at") or "")[:10] for row in rows if row.get("posted_at")]
    newest = max(dates) if dates else None
    warning = None
    if newest:
        days_old = (datetime.now(timezone.utc).date() - date.fromisoformat(newest)).days
        if days_old > 7:
            warning = (
                f"Synced Instagram library newest post is {newest} ({days_old} days behind UTC today). "
                "An empty recent cohort may mean stale sync, not that publishing stopped."
            )
    return {
        "library_post_count": len(rows),
        "library_newest_posted_at": newest,
        "staleness_warning": warning,
    }

