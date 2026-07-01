"""Pydantic models for TikTok marketing dataset."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TikTokMetrics(BaseModel):
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    saves: int | None = None
    shares: int | None = None
    duration_sec: int | None = None
    saves_per_1k_views: float | None = None
    comments_per_1k_views: float | None = None
    shares_per_1k_views: float | None = None


class TikTokPost(BaseModel):
    video_id: str
    url: str
    posted_at: str | None = None
    caption: str | None = None
    duration_sec: int | None = None
    format_guess: str = "video"
    metrics: TikTokMetrics = Field(default_factory=TikTokMetrics)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class TikTokTranscript(BaseModel):
    video_id: str
    full_text: str | None = None
    segments: list[dict[str, Any]] = Field(default_factory=list)
    model: str | None = None
    status: str = "pending"


class TikTokHook(BaseModel):
    video_id: str
    spoken_hook: str | None = None
    caption_hook: str | None = None
    onscreen_hook: str | None = None
    hook_source: str = "spoken"
    confidence: float = 1.0


class TikTokComment(BaseModel):
    video_id: str
    comment_id: str
    text: str
    likes: int = 0
    replies: int = 0
    created_at: str | None = None
    themes: list[str] = Field(default_factory=list)


class TikTokCommentAnalysis(BaseModel):
    video_id: str
    themes: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    content_requests: list[str] = Field(default_factory=list)
    emotional_pattern: str | None = None
    suggested_future_angles: list[str] = Field(default_factory=list)
    primary_theme: str | None = None


class PerformanceDifference(BaseModel):
    views_delta: int | None = None
    saves_per_1k_delta: float | None = None
    likes_delta: int | None = None


class TikTokABPair(BaseModel):
    pair_id: str
    video_a: str
    video_b: str
    similarity_basis: str
    hook_difference: str | None = None
    performance_difference: PerformanceDifference = Field(default_factory=PerformanceDifference)
    learning: str | None = None


class TikTokVideoRecord(BaseModel):
    post: TikTokPost
    transcript: TikTokTranscript
    hook: TikTokHook
    comments: list[TikTokComment] = Field(default_factory=list)
    comment_analysis: TikTokCommentAnalysis | None = None
    ab_pairs: list[dict[str, Any]] = Field(default_factory=list)


class TikTokMarketingDataset(BaseModel):
    dataset_version: str = "1"
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    videos: dict[str, TikTokVideoRecord] = Field(default_factory=dict)
    ab_pairs: list[TikTokABPair] = Field(default_factory=list)
