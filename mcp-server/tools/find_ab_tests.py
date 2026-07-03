"""Filter and return TikTok A/B hook tests from content_posts."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from tools.tiktok_shared import aggregate_ab_tests, fetch_tiktok_posts, saves_per_1k


def find_ab_tests(
    *,
    min_views: int = 0,
    hook_source: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    summary = f"min_views={min_views} hook_source={hook_source} since={since} limit={limit}"
    try:
        rows = fetch_tiktok_posts(limit=200)
        posted_by_video = {str(r.get("platform_post_id")): r.get("posted_at") for r in rows}
        tests = aggregate_ab_tests(rows)

        if since:
            tests = [
                t
                for t in tests
                if (str(posted_by_video.get(str(t.get("video_id")) or "") or "")[:10] >= since)
                or (str(posted_by_video.get(str(t.get("partner_video_id")) or "") or "")[:10] >= since)
            ]

        if min_views > 0:
            tests = [
                t
                for t in tests
                if int((t.get("video_metrics") or {}).get("views") or 0) >= min_views
                or int((t.get("partner_metrics") or {}).get("views") or 0) >= min_views
            ]

        if hook_source:
            tests = [
                t
                for t in tests
                if t.get("video_hook_source") == hook_source
                or t.get("partner_hook_source") == hook_source
            ]

        tests.sort(
            key=lambda t: max(t.get("video_saves_per_1k") or 0, t.get("partner_saves_per_1k") or 0),
            reverse=True,
        )

        result = {
            "ab_tests": tests[:limit],
            "count": len(tests),
            "filters": {
                "min_views": min_views,
                "hook_source": hook_source,
                "since": since,
                "limit": limit,
            },
        }
        log_tool_call(tool_name="find_ab_tests", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="find_ab_tests",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise
