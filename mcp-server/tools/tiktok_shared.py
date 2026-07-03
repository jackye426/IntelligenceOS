"""Shared TikTok content_posts helpers for MCP tools."""

from __future__ import annotations

from typing import Any

from common.supabase_client import get_client


def fetch_tiktok_posts(*, limit: int = 200) -> list[dict[str, Any]]:
    return (
        get_client()
        .table("content_posts")
        .select(
            "id, platform_post_id, title, post_url, posted_at, hook, metrics, metadata, topic"
        )
        .eq("platform", "tiktok")
        .limit(limit)
        .execute()
        .data
        or []
    )


def saves_per_1k(metrics: dict[str, Any]) -> float:
    if metrics.get("saves_per_1k_views") is not None:
        return float(metrics["saves_per_1k_views"])
    views = metrics.get("views")
    saves = metrics.get("saves")
    if views and saves:
        return round((saves / views) * 1000, 2)
    return 0.0


def aggregate_ab_tests(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
            hook_detail = meta.get("hook_detail") or {}
            partner_meta = partner.get("metadata") or {}
            partner_hook_detail = partner_meta.get("hook_detail") or {}
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
                "video_hook_source": hook_detail.get("hook_source"),
                "partner_hook_source": partner_hook_detail.get("hook_source"),
                "video_saves_per_1k": saves_per_1k(row.get("metrics") or {}),
                "partner_saves_per_1k": saves_per_1k(partner.get("metrics") or {}),
            }
    return list(by_id.values())
