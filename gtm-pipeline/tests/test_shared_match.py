"""Unit tests for address / name / match_confidence."""

from __future__ import annotations

from gtm_pipeline.shared.address import normalise_postcode, parse_address
from gtm_pipeline.shared.match_confidence import match_confidence
from gtm_pipeline.shared.name import normalise_name


def test_normalise_postcode_spacing():
    assert normalise_postcode("w1g9pf") == "W1G 9PF"
    assert normalise_postcode("W1G 9PF") == "W1G 9PF"
    assert normalise_postcode("10 Harley Street, London, W1G 9PF") == "W1G 9PF"


def test_parse_address_doctify_style():
    parsed = parse_address("0.21 miles | 10 Harley Street, London, United Kingdom, W1G 9PF")
    assert parsed.postcode == "W1G 9PF"
    assert "harley" in parsed.street
    assert parsed.city.lower() == "london"


def test_normalise_name_strips_ltd_clinic():
    assert normalise_name("The Luna Clinic Ltd") == "luna"
    assert "limited" not in normalise_name("BBH Medical Solutions Limited")


def test_match_confidence_with_phone_weights():
    result = match_confidence(
        {"name": "Luna Clinic", "phone": "02071234567", "postcode": "W1G 9PF"},
        {"name": "The Luna Clinic", "phone": "+442071234567", "postcode": "W1G 9PF"},
    )
    assert result.phone_present is True
    assert result.confidence >= 0.9
    assert any(r.startswith("phone=") for r in result.reasons)


def test_match_confidence_without_phone_name_heavy():
    result = match_confidence(
        {"name": "London Gynaecology", "postcode": "W1G 6BG"},
        {"name": "London Gynaecology Harley Street", "postcode": "W1G 6BG"},
    )
    assert result.phone_present is False
    assert result.confidence >= 0.7
    assert any("0.80" in r for r in result.reasons)


def test_match_confidence_website_bonus():
    weak = match_confidence(
        {"name": "Alpha", "website": "https://alpha.example"},
        {"name": "Beta", "website": "https://alpha.example"},
    )
    base = match_confidence(
        {"name": "Alpha"},
        {"name": "Beta"},
    )
    assert weak.confidence >= base.confidence
