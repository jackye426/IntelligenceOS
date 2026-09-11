"""Tests for fetch_catalog stage."""

import pytest

from marketing_pipeline.tiktok.stages.fetch_catalog import entry_to_row, parse_since


def test_parse_since():
    ts = parse_since("2026-04-20")
    assert ts > 0


def test_entry_to_row():
    row = entry_to_row(
        {
            "id": "123",
            "timestamp": 1713571200,
            "title": "Test hook",
            "view_count": 1000,
        }
    )
    assert row["video_id"] == "123"
    assert "tiktok.com" in row["url"]


def test_fetch_playlist_rejects_bare_null(monkeypatch):
    """yt-dlp exits 0 and prints `null` when an extraction yields nothing.

    Returning that as the playlist produced an AttributeError three frames later
    with no clue why, so a null payload must be treated as a failed attempt.
    """
    import subprocess

    from marketing_pipeline.tiktok.stages import fetch_catalog as fc

    calls = {"n": 0}

    class _Proc:
        returncode = 0
        stdout = b"null\n"
        stderr = b""

    def fake_run(*_a, **_k):
        calls["n"] += 1
        return _Proc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(fc.time, "sleep", lambda *_: None)

    with pytest.raises(RuntimeError, match="instead of a playlist"):
        fc.fetch_playlist(handle="someone", attempts=2)
    assert calls["n"] == 2, "a null payload should be retried, not accepted"


def test_fetch_playlist_accepts_partial_json_despite_exit_code(monkeypatch):
    """A non-zero exit that still produced entries is usable."""
    import json as _json
    import subprocess

    from marketing_pipeline.tiktok.stages import fetch_catalog as fc

    class _Proc:
        returncode = 1
        stdout = _json.dumps({"entries": [{"id": "1"}]}).encode()
        stderr = b"some warning"

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Proc())
    monkeypatch.setattr(fc.time, "sleep", lambda *_: None)
    assert fc.fetch_playlist(handle="someone")["entries"] == [{"id": "1"}]


def test_fetch_playlist_reports_stderr_on_total_failure(monkeypatch):
    import subprocess

    from marketing_pipeline.tiktok.stages import fetch_catalog as fc

    class _Proc:
        returncode = 1
        stdout = b""
        stderr = b"ERROR: Unable to extract webpage: rate limited"

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Proc())
    monkeypatch.setattr(fc.time, "sleep", lambda *_: None)
    with pytest.raises(RuntimeError, match="rate limited"):
        fc.fetch_playlist(handle="someone", attempts=2)
