"""Suggest hook repackaging for an underperforming TikTok video using top performers."""

from __future__ import annotations

from typing import Any, Literal

from common.audit import log_tool_call
from common.openrouter_client import chat_completion
from tools.get_tiktok_video import get_tiktok_video
from tools.tiktok_shared import SortBy, fetch_tiktok_posts, post_summary, rank_posts
from tools.tiktok_strategy_state import brief_excerpt_for_prompt

ReferenceSort = Literal["views", "saves_per_1k", "engagement"]


def _transcript_excerpt(transcript: str | None, *, max_chars: int = 600) -> str:
    if not transcript:
        return ""
    text = transcript.strip()
    return text[:max_chars] + ("…" if len(text) > max_chars else "")


def suggest_hook_repackage(
    video_id: str,
    *,
    reference_video_id: str | None = None,
    reference_sort_by: ReferenceSort = "views",
) -> dict[str, Any]:
    summary = f"video_id={video_id} reference={reference_video_id} sort={reference_sort_by}"
    try:
        target = get_tiktok_video(video_id)
        if not target.get("found"):
            return {"ok": False, "error": f"Video {video_id} not found"}

        rows = fetch_tiktok_posts()
        ranked = rank_posts(rows, reference_sort_by)  # type: ignore[arg-type]

        references: list[dict[str, Any]] = []
        if reference_video_id:
            ref_row = next(
                (r for r in rows if str(r.get("platform_post_id")) == reference_video_id),
                None,
            )
            if ref_row:
                references.append(post_summary(ref_row))
        else:
            # Top by views and by saves/1k as dual references when they differ
            by_views = post_summary(ranked[0]) if ranked else None
            by_saves = post_summary(rank_posts(rows, "saves_per_1k")[0]) if rows else None
            if by_views:
                references.append({**by_views, "reference_reason": f"top_by_{reference_sort_by}"})
            if by_saves and by_saves.get("video_id") != (by_views or {}).get("video_id"):
                references.append({**by_saves, "reference_reason": "top_by_saves_per_1k"})

        ref_details = [get_tiktok_video(str(r["video_id"])) for r in references if r.get("video_id")]
        strategy_context = brief_excerpt_for_prompt()

        system = (
            "You are a TikTok content strategist for DocMap (endometriosis patient education). "
            "Propose hook repackaging only — never suggest posting without human review. "
            "Focus on on-screen hook text and caption opening line. Be specific and concise. "
            "Ground every suggestion in the strategy brief: cite playbook theme, prior learnings, "
            "and open/closed decisions by decision_id when relevant. Prefer closing due decisions "
            "over inventing new experiments."
        )
        user_prompt = f"""
Strategy brief + open decisions (required context):
{strategy_context}

Underperforming video:
- video_id: {video_id}
- post_url: {target.get('post_url')}
- metrics: {target.get('metrics')}
- hook (primary): {target.get('hook')}
- hook_detail: {target.get('hook_detail')}
- caption (first 400 chars): {(target.get('caption') or '')[:400]}
- transcript excerpt: {_transcript_excerpt(target.get('transcript'))}

Reference winner(s):
{ref_details}

Task:
1. Briefly explain what the winner hook pattern is doing (fear/empowerment/specificity).
2. Propose 2-3 alternative on-screen hooks + caption openers for the underperformer that mirror the winner pattern but fit this video's transcript topic.
3. Note which metric gap matters most (views vs saves/1k vs engagement).

Return markdown with sections: Playbook alignment, Pattern, Proposed hooks (numbered), Metric note, Avoids.
""".strip()

        suggestions = chat_completion(system=system, user=user_prompt)

        result = {
            "ok": True,
            "video_id": video_id,
            "underperformer": {
                "hook": target.get("hook"),
                "hook_detail": target.get("hook_detail"),
                "metrics": target.get("metrics"),
                "post_url": target.get("post_url"),
                "transcript_excerpt": _transcript_excerpt(target.get("transcript")),
            },
            "references": references,
            "reference_details": ref_details,
            "suggestions_markdown": suggestions,
            "next_step": (
                "Human approves hooks, films/reposts, then log_tiktok_decision(...) with success_criteria; "
                "later record_decision_outcome(confirmed=true). Optionally record_ab_learning for pair takeaways."
            ),
        }
        log_tool_call(
            tool_name="suggest_hook_repackage",
            request_summary=summary,
            success=True,
            entity_type="content_post",
            entity_id=video_id,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="suggest_hook_repackage",
            request_summary=summary,
            success=False,
            entity_type="content_post",
            entity_id=video_id,
            error=str(exc),
        )
        raise
