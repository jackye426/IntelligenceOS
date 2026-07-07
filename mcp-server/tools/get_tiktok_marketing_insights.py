"""TikTok marketing insights from content_posts metadata."""

from __future__ import annotations

from typing import Any, Literal

from common.audit import log_tool_call
from tools.tiktok_shared import (
    SortBy,
    aggregate_ab_tests,
    cohort_medians,
    fetch_tiktok_posts,
    filter_by_date,
    library_stats,
    post_summary,
    rank_posts,
)

RankingKey = Literal["views", "engagement", "saves_per_1k"]


def get_tiktok_marketing_insights(
    limit: int = 15,
    sort_by: SortBy | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    summary = f"limit={limit} sort_by={sort_by} since={since}"
    try:
        rows = fetch_tiktok_posts()
        if since:
            rows = filter_by_date(rows, since=since)
        stats = library_stats(fetch_tiktok_posts())
        medians = cohort_medians(rows if rows else fetch_tiktok_posts())

        rankings: dict[str, list[dict[str, Any]]] = {}
        for key in ("views", "engagement", "saves_per_1k"):
            ranked = rank_posts(rows, key)  # type: ignore[arg-type]
            rankings[key] = [
                post_summary(row, medians=medians) for row in ranked[:limit]
            ]

        primary_sort: SortBy = sort_by or "saves_per_1k"
        primary_ranked = rank_posts(rows, primary_sort)

        top_posts = []
        for row in primary_ranked[:limit]:
            meta = row.get("metadata") or {}
            hook_detail = meta.get("hook_detail") or {}
            item = post_summary(row, medians=medians)
            item["suggested_angles"] = (meta.get("comment_analysis") or {}).get(
                "suggested_future_angles", []
            )
            item["missing_onscreen_hook"] = not hook_detail.get("onscreen_hook")
            top_posts.append(item)

        result = {
            "top_posts": top_posts,
            "primary_sort_by": primary_sort,
            "rankings": rankings,
            "cohort_median": medians,
            "ab_tests": aggregate_ab_tests(rows, winner_by="views"),
            "video_count": len(rows),
            "since": since,
            **stats,
        }
        log_tool_call(tool_name="get_tiktok_marketing_insights", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_tiktok_marketing_insights",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise
