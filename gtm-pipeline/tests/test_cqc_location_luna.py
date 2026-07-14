"""Offline CQC Luna fixture parse."""

from __future__ import annotations

from pathlib import Path

from gtm_pipeline.cqc_location import parse_location_html

FIXTURE = Path(__file__).parent / "fixtures" / "cqc_luna_1-19271937885.html"


def test_luna_location_parse():
    html = FIXTURE.read_text(encoding="utf-8")
    overview = parse_location_html(
        html, location_url="https://www.cqc.org.uk/location/1-19271937885"
    )
    assert overview.location_id == "1-19271937885"
    assert "Luna" in overview.name
    assert overview.registered_manager == "Dr Bassel Hamameeh Al Wattar"
    assert overview.nominated_individual == "Dr Bassel Hamameeh Al Wattar"
    assert "BBH Medical Solutions Ltd" in overview.provider_name
    assert overview.registered_since is not None
    assert overview.registered_since.isoformat() == "2024-05-01"
    assert any("Family planning" in s for s in overview.specialisms)
