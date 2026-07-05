"""Fetch a single TikTok video with full caption, transcript, hooks, and partners."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from tools.tiktok_shared import fetch_tiktok_post, fetch_tiktok_posts, post_summary


def get_tiktok_video(video_id: str) -> dict[str, Any]:
    summary = f"video_id={video_id}"
    try:
        row = fetch_tiktok_post(video_id)
        if not row:
            result = {"found": False, "video_id": video_id}
            log_tool_call(
                tool_name="get_tiktok_video",
                request_summary=summary,
                success=True,
                entity_type="content_post",
                entity_id=video_id,
            )
            return result

        meta = row.get("metadata") or {}
        hook_detail = meta.get("hook_detail") or {}
        comment_analysis = meta.get("comment_analysis") or {}
        ab_pairs = meta.get("ab_pairs") or []
        ab_learning = meta.get("ab_learning")

        all_posts = fetch_tiktok_posts()
        posts_by_id = {str(p.get("platform_post_id")): p for p in all_posts}

        partners: list[dict[str, Any]] = []
        for ref in ab_pairs:
            partner_id = str(ref.get("partner_video_id") or "")
            partner = posts_by_id.get(partner_id)
            if not partner:
                partners.append({"video_id": partner_id, "found": False})
                continue
            partners.append(
                {
                    "found": True,
                    "pair_id": ref.get("pair_id"),
                    "role": ref.get("role"),
                    "learning": ref.get("learning"),
                    "performance_difference": ref.get("performance_difference"),
                    **post_summary(partner),
                }
            )

        result = {
            "found": True,
            "video_id": video_id,
            "title": row.get("title"),
            "post_url": row.get("post_url"),
            "posted_at": row.get("posted_at"),
            "topic": row.get("topic"),
            "format": row.get("format"),
            "hook": row.get("hook"),
            "hook_detail": hook_detail,
            "caption": row.get("caption"),
            "transcript": row.get("transcript"),
            "metrics": row.get("metrics") or {},
            "comment_analysis": comment_analysis,
            "ab_pairs": ab_pairs,
            "ab_learning": ab_learning,
            "partners": partners,
            "performance_tier": meta.get("performance_tier"),
        }
        log_tool_call(
            tool_name="get_tiktok_video",
            request_summary=summary,
            success=True,
            entity_type="content_post",
            entity_id=video_id,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_tiktok_video",
            request_summary=summary,
            success=False,
            entity_type="content_post",
            entity_id=video_id,
            error=str(exc),
        )
        raise
