"""Read the Instagram strategy brief from Supabase."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from common.supabase_client import get_client


def get_instagram_strategy_brief() -> dict[str, Any]:
    try:
        rows = (
            get_client()
            .table("content_posts")
            .select("metadata, posted_at")
            .eq("platform", "instagram")
            .eq("platform_post_id", "instagram-strategy-state")
            .limit(1)
            .execute()
            .data
            or []
        )
        if not rows:
            result = {
                "found": False,
                "message": "Instagram strategy brief not synced yet. Run instagram export && instagram sync-supabase.",
            }
        else:
            meta = rows[0].get("metadata") or {}
            result = {"found": True, "posted_at": rows[0].get("posted_at"), **(meta.get("strategy_brief") or {})}
        log_tool_call(tool_name="get_instagram_strategy_brief", request_summary="", success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_instagram_strategy_brief",
            request_summary="",
            success=False,
            error=str(exc),
        )
        raise

