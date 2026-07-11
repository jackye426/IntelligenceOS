"""Instagram marketing rankings and format breakdowns."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from tools.instagram_shared import (
    InstagramSortBy,
    fetch_instagram_posts,
    filter_by_date,
    post_summary,
    rank_posts,
)


def get_instagram_marketing_insights(
    limit: int = 15,
    sort_by: InstagramSortBy = "intent",
    since: str | None = None,
) -> dict[str, Any]:
    summary = f"limit={limit} sort_by={sort_by} since={since}"
    try:
        rows = fetch_instagram_posts()
        cohort = filter_by_date(rows, since=since)
        format_counts: dict[str, int] = {}
        for row in cohort:
            fmt = str(row.get("format") or "unknown")
            format_counts[fmt] = format_counts.get(fmt, 0) + 1
        result = {
            "since": since,
            "sort_by": sort_by,
            "format_counts": format_counts,
            "rankings": [post_summary(row) for row in rank_posts(cohort, sort_by)[:limit]],
            "top_by_format": {},
        }
        for fmt in ("reel", "carousel", "static", "unknown"):
            subset = [row for row in cohort if row.get("format") == fmt]
            if subset:
                result["top_by_format"][fmt] = [
                    post_summary(row) for row in rank_posts(subset, sort_by)[:5]
                ]
        log_tool_call(
            tool_name="get_instagram_marketing_insights",
            request_summary=summary,
            success=True,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_instagram_marketing_insights",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise

