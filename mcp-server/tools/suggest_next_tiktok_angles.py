"""Suggest next TikTok content angles from comment analysis."""

from __future__ import annotations

from collections import Counter
from typing import Any

from common.audit import log_tool_call
from tools.tiktok_shared import fetch_tiktok_posts, saves_per_1k
from tools.tiktok_strategy_state import brief_excerpt_for_prompt


def suggest_next_tiktok_angles(
    *,
    limit: int = 15,
    min_post_saves_per_1k: float = 0.0,
) -> dict[str, Any]:
    summary = f"limit={limit} min_post_saves_per_1k={min_post_saves_per_1k}"
    try:
        rows = fetch_tiktok_posts(limit=200)
        angle_scores: Counter[str] = Counter()
        angle_sources: dict[str, list[dict[str, Any]]] = {}

        for row in rows:
            metrics = row.get("metrics") or {}
            if saves_per_1k(metrics) < min_post_saves_per_1k:
                continue
            meta = row.get("metadata") or {}
            analysis = meta.get("comment_analysis") or {}
            angles = analysis.get("suggested_future_angles") or []
            weight = max(saves_per_1k(metrics), 1.0)
            for angle in angles:
                text = str(angle).strip()
                if not text:
                    continue
                angle_scores[text] += weight
                angle_sources.setdefault(text, []).append(
                    {
                        "video_id": row.get("platform_post_id"),
                        "hook": row.get("hook"),
                        "saves_per_1k_views": saves_per_1k(metrics),
                        "post_url": row.get("post_url"),
                    }
                )

        ranked = [
            {
                "angle": angle,
                "score": round(score, 2),
                "source_videos": angle_sources.get(angle, [])[:3],
            }
            for angle, score in angle_scores.most_common(limit)
        ]

        result = {
            "suggested_angles": ranked,
            "count": len(ranked),
            "filters": {"limit": limit, "min_post_saves_per_1k": min_post_saves_per_1k},
            "strategy_brief_excerpt": brief_excerpt_for_prompt(max_chars=4000),
            "output_sections": ["Playbook alignment", "Builds on", "Hypothesis", "Avoids"],
        }
        log_tool_call(tool_name="suggest_next_tiktok_angles", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="suggest_next_tiktok_angles",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise
