"""TikTok marketing insights from content_posts metadata."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from common.supabase_client import get_client


def _saves_per_1k(metrics: dict[str, Any]) -> float:
    if metrics.get("saves_per_1k_views") is not None:
        return float(metrics["saves_per_1k_views"])
    views = metrics.get("views")
    saves = metrics.get("saves")
    if views and saves:
        return round((saves / views) * 1000, 2)
    return 0.0


def _aggregate_ab_tests(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    posts_by_video: dict[str, dict[str, Any]] = {}

    for row in rows:
        vid = row.get("platform_post_id")
        if vid:
            posts_by_video[str(vid)] = row

    for row in rows:
        meta = row.get("metadata") or {}
        for ref in meta.get("ab_pairs") or []:
            pair_id = ref.get("pair_id")
            if not pair_id or pair_id in by_id:
                continue
            partner_id = str(ref.get("partner_video_id") or "")
            partner = posts_by_video.get(partner_id, {})
            by_id[pair_id] = {
                "pair_id": pair_id,
                "video_id": row.get("platform_post_id"),
                "partner_video_id": partner_id,
                "learning": ref.get("learning"),
                "performance_difference": ref.get("performance_difference"),
                "video_metrics": row.get("metrics") or {},
                "partner_metrics": partner.get("metrics") or {},
                "video_hook": row.get("hook"),
                "partner_hook": partner.get("hook"),
            }
    return list(by_id.values())


def get_tiktok_marketing_insights(limit: int = 10) -> dict[str, Any]:
    summary = f"limit={limit}"
    try:
        rows = (
            get_client()
            .table("content_posts")
            .select(
                "id, platform_post_id, title, post_url, posted_at, hook, metrics, metadata, topic"
            )
            .eq("platform", "tiktok")
            .limit(200)
            .execute()
            .data
            or []
        )

        ranked = sorted(rows, key=lambda r: _saves_per_1k(r.get("metrics") or {}), reverse=True)
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
            "ab_tests": _aggregate_ab_tests(rows),
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
