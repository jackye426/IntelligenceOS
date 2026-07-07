"""Tests for strategy brief assembly."""

from marketing_pipeline.tiktok.models import (
    TikTokHook,
    TikTokMarketingDataset,
    TikTokMetrics,
    TikTokPost,
    TikTokTranscript,
    TikTokVideoRecord,
)
from marketing_pipeline.tiktok.stages.build_strategy_brief import build_strategy_brief


def _video(vid: str, views: int, saves: int) -> TikTokVideoRecord:
    return TikTokVideoRecord(
        post=TikTokPost(
            video_id=vid,
            url=f"https://tiktok.com/@docmap/video/{vid}",
            posted_at="2026-06-01T12:00:00+00:00",
            metrics=TikTokMetrics(
                views=views,
                likes=10,
                comments=2,
                shares=1,
                saves=saves,
                saves_per_1k_views=round((saves / views) * 1000, 2) if views else 0,
            ),
        ),
        transcript=TikTokTranscript(video_id=vid, status="complete"),
        hook=TikTokHook(video_id=vid, spoken_hook=f"hook-{vid}"),
    )


def test_build_strategy_brief_includes_constitution_and_reference_set():
    dataset = TikTokMarketingDataset(
        generated_at="2026-07-06T00:00:00+00:00",
        videos={
            "a": _video("a", 100_000, 500),
            "b": _video("b", 1_000, 200),
        },
    )
    brief = build_strategy_brief(dataset)
    assert "instructions_for_claude" in brief["meta"]
    assert brief["meta"]["video_count"] == 2
    assert isinstance(brief["1_constitution"], str)
    assert len(brief["reference_set"]) >= 2
    assert brief["5_anti_patterns"]
