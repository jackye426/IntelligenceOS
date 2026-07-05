"""TikTok cohort review — date-filtered posts with performance tiers."""

from __future__ import annotations

from typing import Any, Literal

from common.audit import log_tool_call
from tools.tiktok_shared import (
    SortBy,
    cohort_medians,
    fetch_tiktok_posts,
    filter_by_date,
    performance_tier,
    post_summary,
    rank_posts,
)

TierFilter = Literal["all", "outperform", "underperform", "typical"]


def get_tiktok_cohort(
    since: str | None = None,
    until: str | None = None,
    sort_by: SortBy = "views",
    limit: int = 50,
    tier: TierFilter = "all",
) -> dict[str, Any]:
    summary = f"since={since} until={until} sort_by={sort_by} limit={limit} tier={tier}"
    try:
        rows = fetch_tiktok_posts()
        cohort_rows = filter_by_date(rows, since=since, until=until)
        medians = cohort_medians(cohort_rows if cohort_rows else rows)

        ranked = rank_posts(cohort_rows, sort_by)
        posts: list[dict[str, Any]] = []
        for row in ranked:
            tier_views = performance_tier(row, medians, sort_by="views")
            tier_saves = performance_tier(row, medians, sort_by="saves_per_1k")
            item = post_summary(row, medians=medians)
            item["tier_vs_cohort"] = {
                "views": tier_views,
                "saves_per_1k": tier_saves,
                "primary_sort_by": sort_by,
                "primary_tier": performance_tier(row, medians, sort_by=sort_by),
            }
            primary_tier = item["tier_vs_cohort"]["primary_tier"]
            if tier != "all" and primary_tier != tier:
                continue
            posts.append(item)
            if len(posts) >= limit:
                break

        result = {
            "since": since,
            "until": until,
            "sort_by": sort_by,
            "tier_filter": tier,
            "cohort_median": medians,
            "catalog_size": len(rows),
            "cohort_size": len(cohort_rows),
            "posts": posts,
            "count": len(posts),
        }
        log_tool_call(tool_name="get_tiktok_cohort", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_tiktok_cohort",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise
