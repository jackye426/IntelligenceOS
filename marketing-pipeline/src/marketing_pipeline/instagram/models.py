"""Pydantic models for the Instagram marketing dataset."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

InstagramFormat = Literal["reel", "carousel", "static", "unknown"]


class InstagramMetrics(BaseModel):
    likes: int | None = None
    comments: int | None = None
    views: int | None = None
    plays: int | None = None
    reach: int | None = None
    saves: int | None = None
    shares: int | None = None
    profile_visits: int | None = None
    follows: int | None = None
    external_link_taps: int | None = None
    avg_watch_time_sec: float | None = None
    skip_rate: float | None = None
    engagement: int | None = None
    engagement_per_1k: float | None = None
    saves_per_1k: float | None = None
    shares_per_1k: float | None = None
    comments_per_1k: float | None = None


class InstagramComponents(BaseModel):
    format: InstagramFormat = "unknown"
    cover_hook: str | None = None
    caption_opening: str | None = None
    topic: str | None = None
    content_bucket: str | None = None
    featured_person: str | None = None
    cta: str | None = None
    funnel_stage: str = "unclear"
    creative_pattern: str | None = None
    save_reason: str | None = None
    comment_theme: str | None = None
    visual_structure: str | None = None
    slide_count: int | None = None
    cover_claim: str | None = None
    slide_pattern: str | None = None
    final_cta: str | None = None
    saveability: str | None = None
    speaker: str | None = None
    audio_type: str | None = None
    transcript_status: str = "unavailable"
    opening_line: str | None = None
    watch_metric_layer: str = "missing"
    source_layers: list[str] = Field(default_factory=list)


class InstagramComment(BaseModel):
    comment_id: str
    text: str
    owner_username: str | None = None
    likes: int = 0
    replies: int = 0
    created_at: str | None = None


class InstagramPost(BaseModel):
    post_id: str
    shortcode: str | None = None
    url: str
    posted_at: str | None = None
    caption: str | None = None
    title: str | None = None
    topic: str | None = None
    format: InstagramFormat = "unknown"
    media_type: str | None = None
    media_url: str | None = None
    thumbnail_url: str | None = None
    child_media: list[dict[str, Any]] = Field(default_factory=list)
    transcript: str | None = None
    metrics: InstagramMetrics = Field(default_factory=InstagramMetrics)
    components: InstagramComponents = Field(default_factory=InstagramComponents)
    comments: list[InstagramComment] = Field(default_factory=list)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class InstagramMarketingDataset(BaseModel):
    dataset_version: str = "1"
    account: str = "docmapuk"
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    posts: dict[str, InstagramPost] = Field(default_factory=dict)

