"""Content performance lookup."""

from __future__ import annotations

from typing import Any, Literal

from common.audit import log_tool_call
from common.supabase_client import get_client
from tools.tiktok_shared import attach_tiktok_snapshot_metrics, post_summary, rank_posts

PlatformSort = Literal["views", "likes", "engagement", "saves_per_1k", "posted_at"]


def get_content_performance(
    platform: str | None = None,
    limit: int = 20,
    sort_by: PlatformSort = "views",
) -> list[dict[str, Any]]:
    summary = f"platform={platform}, limit={limit}, sort_by={sort_by}"
    try:
        query = get_client().table("content_posts").select(
            "id, platform, platform_post_id, title, post_url, posted_at, topic, format, "
            "hook, caption, metrics, metadata, account_handle, owner_scope"
        )
        if platform:
            query = query.eq("platform", platform)

        if platform == "tiktok":
            query = query.eq("account_handle", "docmap").eq("owner_scope", "docmap")
        elif platform is None:
            query = query.or_(
                "platform.neq.tiktok,and(platform.eq.tiktok,account_handle.eq.docmap,owner_scope.eq.docmap)"
            )

        # Fetch full platform catalog (cap 500); sort client-side for multi-metric support
        rows = query.order("posted_at", desc=True).limit(500).execute().data or []

        # Recheck the scope before joining any snapshot, even if a backend filter regresses.
        tiktok_rows = [row for row in rows if row.get("platform") == "tiktok"]
        if any(row.get("account_handle") != "docmap" or row.get("owner_scope") != "docmap"
               for row in tiktok_rows):
            raise RuntimeError("Generic content performance received out-of-scope TikTok posts")
        refreshed = iter(attach_tiktok_snapshot_metrics(tiktok_rows))
        rows = [next(refreshed) if row.get("platform") == "tiktok" else row for row in rows]

        if sort_by == "posted_at":
            ranked = rows
        else:
            ranked = rank_posts(rows, sort_by)  # type: ignore[arg-type]

        result = [{**post_summary(row), "platform": row.get("platform")} for row in ranked[:limit]]
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

