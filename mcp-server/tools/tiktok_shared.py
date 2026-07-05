"""Shared TikTok content_posts helpers for MCP tools."""

from __future__ import annotations

import statistics
from typing import Any, Literal

from common.supabase_client import get_client

SortBy = Literal[
    "views",
    "likes",
    "engagement",
    "saves_per_1k",
    "comments_per_1k",
    "shares_per_1k",
    "posted_at",
]

WinnerBy = Literal["views", "saves_per_1k", "engagement"]

TIKTOK_POST_COLUMNS = (
    "id, platform_post_id, title, post_url, posted_at, hook, caption, transcript, "
    "metrics, metadata, topic, format"
)


def fetch_tiktok_posts(*, limit: int = 500) -> list[dict[str, Any]]:
    return (
        get_client()
        .table("content_posts")
        .select(TIKTOK_POST_COLUMNS)
        .eq("platform", "tiktok")
        .order("posted_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )


def fetch_tiktok_post(video_id: str) -> dict[str, Any] | None:
    rows = (
        get_client()
        .table("content_posts")
        .select(TIKTOK_POST_COLUMNS)
        .eq("platform", "tiktok")
        .eq("platform_post_id", video_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def saves_per_1k(metrics: dict[str, Any]) -> float:
    if metrics.get("saves_per_1k_views") is not None:
        return float(metrics["saves_per_1k_views"])
    views = metrics.get("views")
    saves = metrics.get("saves")
    if views and saves:
        return round((saves / views) * 1000, 2)
    return 0.0


def comments_per_1k(metrics: dict[str, Any]) -> float:
    if metrics.get("comments_per_1k_views") is not None:
        return float(metrics["comments_per_1k_views"])
    views = metrics.get("views")
    comments = metrics.get("comments")
    if views and comments:
        return round((comments / views) * 1000, 2)
    return 0.0


def shares_per_1k(metrics: dict[str, Any]) -> float:
    if metrics.get("shares_per_1k_views") is not None:
        return float(metrics["shares_per_1k_views"])
    views = metrics.get("views")
    shares = metrics.get("shares")
    if views and shares:
        return round((shares / views) * 1000, 2)
    return 0.0


def engagement_total(metrics: dict[str, Any]) -> float:
    likes = int(metrics.get("likes") or 0)
    comments = int(metrics.get("comments") or 0)
    shares = int(metrics.get("shares") or 0)
    return float(likes + comments + shares)


def sort_score(row: dict[str, Any], sort_by: SortBy) -> float:
    metrics = row.get("metrics") or {}
    if sort_by == "views":
        return float(metrics.get("views") or 0)
    if sort_by == "likes":
        return float(metrics.get("likes") or 0)
    if sort_by == "engagement":
        return engagement_total(metrics)
    if sort_by == "saves_per_1k":
        return saves_per_1k(metrics)
    if sort_by == "comments_per_1k":
        return comments_per_1k(metrics)
    if sort_by == "shares_per_1k":
        return shares_per_1k(metrics)
    posted_at = row.get("posted_at")
    if not posted_at:
        return 0.0
    return float(str(posted_at).replace("Z", "+00:00")[:26].replace("T", "").replace(":", "").replace("-", "") or 0)


def rank_posts(rows: list[dict[str, Any]], sort_by: SortBy) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: sort_score(r, sort_by), reverse=True)


def cohort_medians(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {"views": 0.0, "saves_per_1k": 0.0, "engagement": 0.0}
    views = [float((r.get("metrics") or {}).get("views") or 0) for r in rows]
    saves = [saves_per_1k(r.get("metrics") or {}) for r in rows]
    eng = [engagement_total(r.get("metrics") or {}) for r in rows]
    return {
        "views": statistics.median(views),
        "saves_per_1k": statistics.median(saves),
        "engagement": statistics.median(eng),
    }


def performance_tier(
    row: dict[str, Any],
    medians: dict[str, float],
    *,
    sort_by: SortBy = "views",
) -> str:
    """Return outperform | typical | underperform vs cohort median on sort_by metric."""
    score = sort_score(row, sort_by)
    median = medians.get(sort_by if sort_by in medians else "views", 0.0)
    if median <= 0:
        return "typical"
    ratio = score / median
    if ratio >= 1.25:
        return "outperform"
    if ratio <= 0.75:
        return "underperform"
    return "typical"


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


def post_summary(row: dict[str, Any], *, medians: dict[str, float] | None = None) -> dict[str, Any]:
    metrics = row.get("metrics") or {}
    meta = row.get("metadata") or {}
    hook_detail = meta.get("hook_detail") or {}
    summary: dict[str, Any] = {
        "video_id": row.get("platform_post_id"),
        "title": row.get("title"),
        "hook": row.get("hook"),
        "hook_source": hook_detail.get("hook_source"),
        "spoken_hook": hook_detail.get("spoken_hook"),
        "caption_hook": hook_detail.get("caption_hook"),
        "onscreen_hook": hook_detail.get("onscreen_hook"),
        "topic": row.get("topic"),
        "format": row.get("format"),
        "post_url": row.get("post_url"),
        "posted_at": row.get("posted_at"),
        "metrics": metrics,
        "views": metrics.get("views"),
        "engagement": int(engagement_total(metrics)),
        "saves_per_1k_views": saves_per_1k(metrics),
    }
    if medians is not None:
        summary["tier_vs_cohort_views"] = performance_tier(row, medians, sort_by="views")
        summary["tier_vs_cohort_saves_per_1k"] = performance_tier(
            row, medians, sort_by="saves_per_1k"
        )
    stored_tier = meta.get("performance_tier")
    if stored_tier:
        summary["performance_tier"] = stored_tier
    return summary


def winner_video_id(
    video_id: str,
    partner_id: str,
    video_metrics: dict[str, Any],
    partner_metrics: dict[str, Any],
    *,
    winner_by: WinnerBy,
) -> str:
    if winner_by == "views":
        a = int(video_metrics.get("views") or 0)
        b = int(partner_metrics.get("views") or 0)
    elif winner_by == "engagement":
        a = int(engagement_total(video_metrics))
        b = int(engagement_total(partner_metrics))
    else:
        a = saves_per_1k(video_metrics)
        b = saves_per_1k(partner_metrics)
    if a > b:
        return video_id
    if b > a:
        return partner_id
    return video_id


def aggregate_ab_tests(
    rows: list[dict[str, Any]],
    *,
    winner_by: WinnerBy = "views",
    dedupe_by_pair_id: bool = False,
) -> list[dict[str, Any]]:
    """Return A/B pair edges. Default: all unique video↔partner edges (not collapsed by pair_id)."""
    posts_by_video: dict[str, dict[str, Any]] = {}
    for row in rows:
        vid = row.get("platform_post_id")
        if vid:
            posts_by_video[str(vid)] = row

    tests: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str]] = set()
    seen_pair_ids: set[str] = set()

    for row in rows:
        video_id = str(row.get("platform_post_id") or "")
        meta = row.get("metadata") or {}
        hook_detail = meta.get("hook_detail") or {}
        ab_learning = meta.get("ab_learning") or {}

        for ref in meta.get("ab_pairs") or []:
            pair_id = ref.get("pair_id")
            partner_id = str(ref.get("partner_video_id") or "")
            if not pair_id or not partner_id:
                continue

            edge = tuple(sorted([video_id, partner_id]))
            if edge in seen_edges:
                continue
            if dedupe_by_pair_id and pair_id in seen_pair_ids:
                continue
            seen_edges.add(edge)
            if dedupe_by_pair_id:
                seen_pair_ids.add(pair_id)

            partner = posts_by_video.get(partner_id, {})
            partner_meta = partner.get("metadata") or {}
            partner_hook_detail = partner_meta.get("hook_detail") or {}
            video_metrics = row.get("metrics") or {}
            partner_metrics = partner.get("metrics") or {}

            learning = ref.get("learning")
            if ab_learning.get("pair_id") == pair_id and ab_learning.get("learning"):
                learning = ab_learning["learning"]

            winner = winner_video_id(
                video_id, partner_id, video_metrics, partner_metrics, winner_by=winner_by
            )
            loser = partner_id if winner == video_id else video_id

            tests.append(
                {
                    "pair_id": pair_id,
                    "video_id": video_id,
                    "partner_video_id": partner_id,
                    "learning": learning,
                    "ab_learning": ab_learning if ab_learning.get("pair_id") == pair_id else None,
                    "performance_difference": ref.get("performance_difference"),
                    "video_metrics": video_metrics,
                    "partner_metrics": partner_metrics,
                    "video_hook": row.get("hook"),
                    "partner_hook": partner.get("hook"),
                    "video_hook_detail": hook_detail,
                    "partner_hook_detail": partner_hook_detail,
                    "video_hook_source": hook_detail.get("hook_source"),
                    "partner_hook_source": partner_hook_detail.get("hook_source"),
                    "video_views": video_metrics.get("views"),
                    "partner_views": partner_metrics.get("views"),
                    "video_saves_per_1k": saves_per_1k(video_metrics),
                    "partner_saves_per_1k": saves_per_1k(partner_metrics),
                    "video_engagement": int(engagement_total(video_metrics)),
                    "partner_engagement": int(engagement_total(partner_metrics)),
                    "winner_by": winner_by,
                    "winner_video_id": winner,
                    "loser_video_id": loser,
                }
            )

    return tests
