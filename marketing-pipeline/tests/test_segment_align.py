"""Tests for Whisper segment alignment A/B detection."""

from marketing_pipeline.tiktok.models import (
    TikTokHook,
    TikTokMarketingDataset,
    TikTokMetrics,
    TikTokPost,
    TikTokTranscript,
    TikTokVideoRecord,
)
from marketing_pipeline.tiktok.stages.detect_ab_pairs import detect_ab_pairs
from marketing_pipeline.tiktok.stages.segment_align import (
    ab_posts_on_different_days,
    segment_align_score,
    text_similarity,
)


def test_segment_align_same_audio():
    segs = [
        {"text": "If you're needing to use really strong pain killers, get help."},
        {"text": "If you're passing out on day one and you're in school,"},
        {"text": "then your friends and your teachers should be noticing it"},
    ]
    assert segment_align_score(segs, segs) == 1.0


def test_segment_align_unrelated():
    a = [{"text": "Are you going to look at my diaphragm?"}]
    b = [{"text": "If you have a laparoscopy of somebody who doesn't know"}]
    assert segment_align_score(a, b) < 0.5


def test_same_day_posts_rejected():
    assert ab_posts_on_different_days(
        "2026-05-28T08:56:40+00:00",
        "2026-05-28T12:00:00+00:00",
    ) is False
    assert ab_posts_on_different_days(
        "2026-05-28T08:56:40+00:00",
        "2026-05-29T08:56:40+00:00",
    ) is True


def _video(
    vid: str,
    *,
    hook: str,
    posted_at: str,
    segments: list[dict],
) -> TikTokVideoRecord:
    return TikTokVideoRecord(
        post=TikTokPost(
            video_id=vid,
            url=f"https://www.tiktok.com/@docmap/video/{vid}",
            posted_at=posted_at,
            metrics=TikTokMetrics(views=1000, saves=50, saves_per_1k_views=50.0),
        ),
        transcript=TikTokTranscript(video_id=vid, full_text="spoken body"),
        hook=TikTokHook(video_id=vid, onscreen_hook=hook),
    )


def test_auto_detect_segment_align(tmp_path, monkeypatch):
    from marketing_pipeline.tiktok.stages import segment_align as sa

    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    monkeypatch.setattr(sa.config, "TRANSCRIPTS_DIR", transcripts)

    import json

    shared = [
        {"text": "If you're needing to use really strong pain killers, get help."},
        {"text": "If you're passing out on day one and you're in school,"},
    ]
    (transcripts / "111.json").write_text(
        json.dumps({"segments": shared}), encoding="utf-8"
    )
    (transcripts / "222.json").write_text(
        json.dumps({"segments": shared}), encoding="utf-8"
    )

    ds = TikTokMarketingDataset(
        videos={
            "111": _video(
                "111",
                hook="Hook variant A",
                posted_at="2026-05-01T00:00:00+00:00",
                segments=shared,
            ),
            "222": _video(
                "222",
                hook="Completely different hook B",
                posted_at="2026-05-15T00:00:00+00:00",
                segments=shared,
            ),
            "333": _video(
                "333",
                hook="Other topic",
                posted_at="2026-05-20T00:00:00+00:00",
                segments=[{"text": "Unrelated monologue about MRI scans"}],
            ),
        }
    )
    (transcripts / "333.json").write_text(
        json.dumps({"segments": [{"text": "Unrelated monologue about MRI scans"}]}),
        encoding="utf-8",
    )

    pairs = detect_ab_pairs(ds)
    auto = [p for p in pairs if p.similarity_basis.startswith("segment_align")]
    assert len(auto) == 1
    assert {auto[0].video_a, auto[0].video_b} == {"111", "222"}
    assert text_similarity("Hook variant A", "Completely different hook B") < 0.92
