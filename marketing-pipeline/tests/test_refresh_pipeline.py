"""Tests for write_master_transcripts and per-video COMPLETE files."""

from __future__ import annotations

import json
from pathlib import Path

from marketing_pipeline.tiktok.stages.write_master_transcripts import write_master_transcripts
from marketing_pipeline.tiktok.stages.write_per_video_complete import (
    existing_complete_ids,
    write_complete_transcript,
)


def test_write_complete_transcript(tmp_path):
    write_complete_transcript(
        "123",
        "Hello world.",
        title="Test",
        description="Caption here",
        out_dir=tmp_path,
    )
    path = tmp_path / "123_COMPLETE.txt"
    assert path.exists()
    assert "123" in path.read_text(encoding="utf-8")


def test_existing_complete_ids(tmp_path):
    write_complete_transcript("a", "text", title="t", description="d", out_dir=tmp_path)
    ids = existing_complete_ids(transcripts_dir=tmp_path)
    assert "a" in ids


def test_transcript_json_model_field(tmp_path, monkeypatch):
    import sys
    import types

    from marketing_pipeline.tiktok.stages import transcribe_video as mod
    from marketing_pipeline.tiktok.stages.transcribe_video import transcribe_media

    media = tmp_path / "clip.mp4"
    media.write_bytes(b"\x00" * 100)
    out_dir = tmp_path / "transcripts"
    out_dir.mkdir()

    class FakeSegment:
        def __init__(self, text: str):
            self.start = 0.0
            self.end = 1.0
            self.text = text

    class FakeInfo:
        language = "en"
        duration = 1.0

    class FakeModel:
        def transcribe(self, *args, **kwargs):
            return [FakeSegment("Hello world.")], FakeInfo()

    fake_fw = types.ModuleType("faster_whisper")
    fake_fw.WhisperModel = lambda *a, **k: FakeModel()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_fw)
    monkeypatch.setattr(mod, "is_garbage_transcript", lambda *a, **k: False)

    _rows, text = transcribe_media(media, "vid1", model_size="tiny", out_dir=out_dir)

    payload = json.loads((out_dir / "vid1.json").read_text(encoding="utf-8"))
    assert payload["model"] == "tiny"
    assert payload["whisper_model"] == "tiny"
    assert text == "Hello world."


def test_write_master_transcripts(tmp_path, monkeypatch):
    trans = tmp_path / "transcripts"
    trans.mkdir()
    write_complete_transcript("999", "Hook sentence here.", title="T", description="D", out_dir=trans)
    (trans / "999.json").write_text(
        json.dumps({"full_text": "Hook sentence here."}),
        encoding="utf-8",
    )
    comments = tmp_path / "comments_raw"
    comments.mkdir()
    (comments / "999.json").write_text(
        json.dumps([{"text": "Nice", "digg_count": 5, "reply_comment_total": 0}]),
        encoding="utf-8",
    )

    from marketing_pipeline import config
    from marketing_pipeline.tiktok.stages import write_master_transcripts as mod

    monkeypatch.setattr(config, "TRANSCRIPTS_DIR", trans)
    monkeypatch.setattr(config, "COMMENTS_RAW_DIR", comments)
    monkeypatch.setattr(config, "MASTER_TRANSCRIPTS", trans / "ALL_COMPLETE_TRANSCRIPTS.txt")
    monkeypatch.setattr(config, "YT_META_DIR", tmp_path / "yt_meta")

    def fake_meta(video_id: str, *, cache: bool = True):
        _ = cache
        return {
            "id": video_id,
            "view_count": 1000,
            "like_count": 10,
            "comment_count": 2,
            "repost_count": 1,
            "save_count": 5,
            "duration": 30,
            "timestamp": 1713571200,
            "upload_date": "20240420",
            "title": "T",
            "description": "D",
        }

    monkeypatch.setattr(mod, "fetch_yt_meta", fake_meta)

    result = write_master_transcripts(
        refresh_metrics=False,
        transcripts_dir=trans,
        out_path=trans / "ALL_COMPLETE_TRANSCRIPTS.txt",
    )
    master = Path(result["master_path"])
    text = master.read_text(encoding="utf-8")
    assert "VIDEO 1" in text
    assert "999" in text
    assert "Hook sentence" in text
