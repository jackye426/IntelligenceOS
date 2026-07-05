"""Tests for performance tier and registry-driven A/B pairs."""

from marketing_pipeline.tiktok.models import TikTokMetrics, TikTokPost, TikTokTranscript, TikTokVideoRecord
from marketing_pipeline.tiktok.stages.detect_ab_pairs import detect_ab_pairs
from marketing_pipeline.tiktok.stages.performance_tier import compute_performance_tiers
from marketing_pipeline.tiktok.models import TikTokMarketingDataset, TikTokHook


def _video(vid: str, views: int, saves: int) -> TikTokVideoRecord:
    spk = round((saves / views) * 1000, 2) if views else 0
    return TikTokVideoRecord(
        post=TikTokPost(
            video_id=vid,
            url=f"https://www.tiktok.com/@docmap/video/{vid}",
            metrics=TikTokMetrics(views=views, saves=saves, saves_per_1k_views=spk),
        ),
        transcript=TikTokTranscript(video_id=vid, full_text="body text here " * 20),
        hook=TikTokHook(video_id=vid, onscreen_hook="hook"),
    )


def test_compute_performance_tiers():
    ds = TikTokMarketingDataset(
        videos={
            "a": _video("a", 1000, 50),
            "b": _video("b", 100, 5),
        }
    )
    tiers = compute_performance_tiers(ds)
    assert tiers["a"]["views"] == "outperform"
    assert tiers["b"]["views"] == "underperform"


def test_registry_pairs_detected():
    ds = TikTokMarketingDataset(
        videos={
            "7641554459755089154": _video("7641554459755089154", 1000, 50),
            "7631220659770690818": _video("7631220659770690818", 2000, 100),
        }
    )
    pairs = detect_ab_pairs(ds)
    assert any(p.pair_id == "excision-vs-ablation" for p in pairs)
