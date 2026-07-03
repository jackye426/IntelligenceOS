"""Tests for fetch_catalog stage."""

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
