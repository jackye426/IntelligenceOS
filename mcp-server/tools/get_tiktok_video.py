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

        components = meta.get("components") if isinstance(meta.get("components"), dict) else None
        result = {
            "found": True,
            "video_id": video_id,
            "title": row.get("title"),
            "post_url": row.get("post_url"),
            "posted_at": row.get("posted_at"),
            "posted_at_note": (
                "Cite this UTC publish timestamp only. Do not infer date from video_id."
                if row.get("posted_at")
                else "posted_at missing — do not invent or decode a date from video_id."
            ),
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
            "components": components,
            "components_available": components is not None,
        }
        try:
            from tools.tiktok_metrics_layers import fetch_latest_studio_insight

            studio = fetch_latest_studio_insight(video_id)
            if studio:
                result["studio_insight"] = {
                    "captured_at": studio.get("captured_at"),
                    "metrics": studio.get("metrics") or {},
                }
        except Exception:  # noqa: BLE001
            # Table may not exist until migration 005 is applied
            pass
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
