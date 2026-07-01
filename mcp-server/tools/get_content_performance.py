"""Content performance lookup."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from common.audit import log_tool_call
from common.supabase_client import get_client


def _sort_key(row: dict[str, Any]) -> float:
    metrics = row.get("metrics") or {}
    # Canonical keys per platform (views/likes) — lanes are kept separate.
    for key in ("views", "likes", "saves", "comments"):
        value = metrics.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    posted_at = row.get("posted_at")
    if not posted_at:
        return 0.0
    try:
        return datetime.fromisoformat(str(posted_at).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def get_content_performance(
    platform: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    summary = f"platform={platform}, limit={limit}"
    try:
        query = get_client().table("content_posts").select(
            "id, platform, title, post_url, posted_at, topic, format, hook, metrics"
        )
        if platform:
            query = query.eq("platform", platform)
        rows = query.limit(max(limit * 3, 30)).execute().data or []
        rows.sort(key=_sort_key, reverse=True)

        result = [
            {
                "id": row["id"],
                "platform": row.get("platform"),
                "title": row.get("title"),
                "topic": row.get("topic"),
                "format": row.get("format"),
                "hook": row.get("hook"),
                "post_url": row.get("post_url"),
                "posted_at": row.get("posted_at"),
                "metrics": row.get("metrics") or {},
            }
            for row in rows[:limit]
        ]
        log_tool_call(tool_name="get_content_performance", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_content_performance",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise
