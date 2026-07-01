from __future__ import annotations

from marketing_pipeline.tiktok.models import TikTokHook, TikTokMetrics, TikTokPost, TikTokTranscript, TikTokVideoRecord
from marketing_pipeline.tiktok.stages.extract_hooks import resolve_primary_hook
from marketing_pipeline.tiktok.sync.supabase import _post_payload


def test_primary_hook_priority():
    hook = TikTokHook(
        video_id="1",
        spoken_hook="spoken",
        caption_hook="caption",
        onscreen_hook="onscreen",
    )
    assert resolve_primary_hook(hook) == "onscreen"


def test_post_payload_metadata_source():
    record = TikTokVideoRecord(
        post=TikTokPost(
            video_id="123",
            url="https://www.tiktok.com/@docmap/video/123",
            metrics=TikTokMetrics(views=1000, saves=50, saves_per_1k_views=50.0),
        ),
        transcript=TikTokTranscript(video_id="123", full_text="Hello world.", status="transcribed"),
        hook=TikTokHook(video_id="123", spoken_hook="Hello."),
    )
    payload = _post_payload("123", record)
    assert payload["platform"] == "tiktok"
    assert payload["metadata"]["source"] == "marketing_pipeline"
    assert payload["metrics"]["saves_per_1k_views"] == 50.0
