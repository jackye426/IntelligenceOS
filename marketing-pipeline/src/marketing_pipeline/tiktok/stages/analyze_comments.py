"""Load per-video comment analysis artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from marketing_pipeline.tiktok.models import TikTokComment, TikTokCommentAnalysis

# Resolved per call: a peer library uses the generic vocabulary, so hardcoding
# DocMap's theme names here would leave questions and objections empty.
from marketing_pipeline.tiktok.stages import comment_labels  # noqa: E402

QUESTION_THEMES = comment_labels.QUESTION_THEMES_BY_VOCAB["docmap-endo"]
OBJECTION_THEMES = comment_labels.OBJECTION_THEMES_BY_VOCAB["docmap-endo"]


def load_labeled_comments(analysis_dir: Path, video_id: str) -> list[TikTokComment]:
    path = analysis_dir / f"comments_labeled_{video_id}.json"
    if not path.exists():
        return []

    raw = json.loads(path.read_text(encoding="utf-8"))
    comments: list[TikTokComment] = []
    for item in raw:
        text = item.get("text") or item.get("comment") or ""
        if not text:
            continue
        themes = item.get("themes") or []
        if isinstance(themes, str):
            themes = [themes]
        comments.append(
            TikTokComment(
                video_id=video_id,
                comment_id=str(item.get("cid") or item.get("comment_id") or ""),
                text=text,
                likes=int(item.get("digg_count") or item.get("likes") or 0),
                replies=int(item.get("reply_comment_total") or item.get("replies") or 0),
                themes=themes,
            )
        )
    comments.sort(key=lambda c: c.likes, reverse=True)
    return comments


def build_comment_analysis(
    video_id: str,
    comments: list[TikTokComment],
    summary_path: Path | None = None,
) -> TikTokCommentAnalysis:
    theme_counts: dict[str, int] = {}
    questions: list[str] = []
    objections: list[str] = []
    content_requests: list[str] = []

    question_set = comment_labels.question_themes()
    objection_set = comment_labels.objection_themes()

    for comment in comments:
        for theme in comment.themes:
            theme_counts[theme] = theme_counts.get(theme, 0) + 1
        if "?" in comment.text:
            questions.append(comment.text[:300])
        for theme in comment.themes:
            if theme in question_set and comment.text not in questions:
                questions.append(comment.text[:300])
            if theme in objection_set and comment.text not in objections:
                objections.append(comment.text[:300])

    primary = max(theme_counts, key=theme_counts.get) if theme_counts else None
    top_themes = sorted(theme_counts, key=theme_counts.get, reverse=True)[:8]

    suggested: list[str] = []
    if summary_path and summary_path.exists():
        summaries = json.loads(summary_path.read_text(encoding="utf-8"))
        for row in summaries:
            if str(row.get("video_id")) == video_id:
                dist = row.get("theme_distribution") or {}
                for theme, count in sorted(dist.items(), key=lambda x: x[1], reverse=True)[:3]:
                    suggested.append(f"Audience interest in {theme.replace('_', ' ')} ({count} comments)")

    return TikTokCommentAnalysis(
        video_id=video_id,
        themes=top_themes,
        questions=questions[:10],
        objections=objections[:10],
        content_requests=content_requests,
        suggested_future_angles=suggested[:5],
        primary_theme=primary,
    )
