"""Composite TikTok content briefing for MCP clients."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from common.supabase_client import get_client
from tools.get_tiktok_marketing_insights import get_tiktok_marketing_insights
from tools.search_knowledge import search_knowledge


def get_tiktok_content_briefing(
    topic: str | None = None,
    *,
    limit: int = 5,
) -> dict[str, Any]:
    query = topic or "endometriosis TikTok content strategy patient action hooks"
    summary = f"topic={topic!r}, limit={limit}"
    try:
        performance = get_tiktok_marketing_insights(limit=limit)
        strategy = search_knowledge(query, entity_type="marketing_playbook", match_count=3)
        audience = search_knowledge(
            "patient questions comments themes",
            entity_type="marketing_comment_digest",
            match_count=3,
        )

        runs = (
            get_client()
            .table("data_ingestion_runs")
            .select("job_name, status, started_at, rows_seen, rows_inserted, rows_updated")
            .eq("job_name", "tiktok_marketing_sync")
            .order("started_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )

        missing_ocr = [
            row.get("video_id")
            for row in performance.get("top_posts", [])
            if not row.get("onscreen_hook")
        ]

        result = {
            "topic": query,
            "performance": performance,
            "strategy_excerpts": strategy,
            "audience_voice": audience,
            "missing_onscreen_hook_in_top": missing_ocr,
            "last_sync_run": runs[0] if runs else None,
        }
        log_tool_call(tool_name="get_tiktok_content_briefing", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_tiktok_content_briefing",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise
