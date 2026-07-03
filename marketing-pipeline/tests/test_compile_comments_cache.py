"""Tests for compile_complete_transcripts comments_raw cache path."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_compile_module():
    root = Path(__file__).resolve().parents[2]
    script = (
        root
        / "Social media analysis"
        / "tiktok_analysis"
        / "scripts"
        / "compile_complete_transcripts.py"
    )
    spec = importlib.util.spec_from_file_location("compile_complete_transcripts", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["compile_complete_transcripts"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_load_comments_from_pipeline_raw(tmp_path, monkeypatch):
    mod = _load_compile_module()
    raw_dir = tmp_path / "comments_raw"
    raw_dir.mkdir()
    comments = [{"text": "Great video", "digg_count": 10, "reply_comment_total": 1}]
    (raw_dir / "123.json").write_text(json.dumps(comments), encoding="utf-8")
    monkeypatch.setattr(mod, "PIPELINE_COMMENTS_RAW", raw_dir)
    monkeypatch.setattr(mod, "_comments_raw_dirs", lambda: [raw_dir])
    loaded = mod.load_comments_from_raw("123")
    assert loaded is not None
    assert loaded[0]["text"] == "Great video"
