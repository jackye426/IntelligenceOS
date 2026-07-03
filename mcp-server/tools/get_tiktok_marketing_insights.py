"""TikTok marketing insights from content_posts metadata."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from tools.tiktok_shared import aggregate_ab_tests, fetch_tiktok_posts, saves_per_1k


def get_tiktok_marketing_insights(limit: int = 10) -> dict[str, Any]:
    summary = f"limit={limit}"
    try:
        rows = fetch_tiktok_posts(limit=200)

        ranked = sorted(rows, key=lambda r: saves_per_1k(r.get("metrics") or {}), reverse=True)
        top_posts = []
        for row in ranked[:limit]:
            meta = row.get("metadata") or {}
            hook_detail = meta.get("hook_detail") or {}
            top_posts.append(
                {
                    "video_id": row.get("platform_post_id"),
                    "title": row.get("title"),
                    "hook": row.get("hook"),
                    "hook_source": hook_detail.get("hook_source"),
                    "spoken_hook": hook_detail.get("spoken_hook"),
                    "caption_hook": hook_detail.get("caption_hook"),
                    "onscreen_hook": hook_detail.get("onscreen_hook"),
                    "missing_onscreen_hook": not hook_detail.get("onscreen_hook"),
                    "topic": row.get("topic"),
                    "post_url": row.get("post_url"),
                    "posted_at": row.get("posted_at"),
                    "metrics": row.get("metrics") or {},
                    "suggested_angles": (meta.get("comment_analysis") or {}).get(
                        "suggested_future_angles", []
                    ),
                }
            )

        result = {
            "top_posts": top_posts,
            "ab_tests": aggregate_ab_tests(rows),
            "video_count": len(rows),
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
