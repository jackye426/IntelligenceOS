"""Tests for catalog datetime resolution."""

from marketing_pipeline.tiktok.stages.posted_at import resolve_posted_at


def test_catalog_datetime_overrides_midnight_parsed():
    posted = resolve_posted_at(
        "123",
        catalog_entry={"post_datetime_utc": "2026-07-02T17:56:00+00:00"},
        parsed_posted_at="2026-07-02T00:00:00+00:00",
    )
    assert posted == "2026-07-02T17:56:00+00:00"


def test_fallback_to_parsed_when_no_catalog():
    posted = resolve_posted_at(
        "123",
        catalog_entry=None,
        parsed_posted_at="2026-06-14T00:00:00+00:00",
    )
    assert posted == "2026-06-14T00:00:00+00:00"


def test_catalog_without_datetime_falls_back():
    posted = resolve_posted_at(
        "123",
        catalog_entry={"caption": "hello"},
        parsed_posted_at="2026-06-14T00:00:00+00:00",
    )
    assert posted == "2026-06-14T00:00:00+00:00"
