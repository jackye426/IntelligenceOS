"""Instagram cohort review."""

from __future__ import annotations

from typing import Any, Literal

from common.audit import log_tool_call
from tools.instagram_shared import (
    InstagramSortBy,
    cohort_medians,
    fetch_instagram_posts,
    filter_by_date,
    library_stats,
    performance_tier,
    post_summary,
    rank_posts,
)

TierFilter = Literal["all", "outperform", "underperform", "typical"]


def get_instagram_cohort(
    since: str | None = None,
    until: str | None = None,
    sort_by: InstagramSortBy = "intent",
    limit: int = 50,
    format: str | None = None,
    tier: TierFilter = "all",
) -> dict[str, Any]:
    summary = f"since={since} until={until} sort_by={sort_by} limit={limit} format={format}"
    try:
        rows = fetch_instagram_posts()
        cohort_rows = filter_by_date(rows, since=since, until=until)
        if format:
            cohort_rows = [row for row in cohort_rows if row.get("format") == format]
        medians = cohort_medians(cohort_rows if cohort_rows else rows)
        posts: list[dict[str, Any]] = []
        for row in rank_posts(cohort_rows, sort_by):
            item = post_summary(row, medians=medians)
            item["tier_vs_cohort"] = {
                "primary_sort_by": sort_by,
                "primary_tier": performance_tier(row, medians, sort_by=sort_by),
            }
            if tier != "all" and item["tier_vs_cohort"]["primary_tier"] != tier:
                continue
            posts.append(item)
            if len(posts) >= limit:
                break
        result = {
            "since": since,
            "until": until,
            "sort_by": sort_by,
            "format_filter": format,
            "tier_filter": tier,
            "cohort_median": medians,
            "cohort_size": len(cohort_rows),
            "posts": posts,
            "count": len(posts),
            **library_stats(rows),
        }
        if not posts and since and result.get("staleness_warning"):
            result["empty_cohort_note"] = (
                "No Instagram posts matched the date filter. Check staleness_warning "
                "before concluding publishing stopped."
            )
        log_tool_call(tool_name="get_instagram_cohort", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_instagram_cohort",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise

