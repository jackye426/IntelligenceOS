"""Tests for CQC person matching + scoped CSV payload mapping."""

from __future__ import annotations

from gtm_pipeline.person_resolve import match_cqc_people_to_candidates, score_person_pair
from gtm_pipeline.sync.scoped_csv import row_to_intelligence_payload


def test_score_person_exact():
    assert score_person_pair("Dr Bassel Hamameeh Al Wattar", "Bassel Al Wattar") >= 0.82


def test_score_person_rejects_different_last_name():
    assert score_person_pair("Mr John Reay", "John Smith") < 0.5


def test_match_cqc_people_to_candidates():
    hits = match_cqc_people_to_candidates(
        nominated_individual="Dr Bassel Hamameeh Al Wattar",
        registered_manager="Dr Bassel Hamameeh Al Wattar",
        candidates=[
            {"practitioner_id": "p1", "full_name": "Bassel Al Wattar", "email": "a@b.c"},
            {"practitioner_id": "p2", "full_name": "Jane Doe", "email": ""},
        ],
    )
    # RM == NI → single query
    assert len(hits) == 1
    assert hits[0].practitioner_id == "p1"
    assert hits[0].confidence >= 0.82


def test_row_to_intelligence_payload_maps_cqc():
    payload = row_to_intelligence_payload(
        {
            "clinic_name": "The Luna Clinic",
            "doctify_profile_url": "https://www.doctify.com/uk/practice/the-luna-clinic",
            "website_url": "https://thelunaclinic.com/",
            "location": "London, W1G 9PB",
            "specialty_tags": "Gynaecology; Fertility",
            "specialist_count": "3",
            "cqc_location_id": "1-19271937885",
            "cqc_registered_manager": "Dr Bassel Hamameeh Al Wattar",
            "cqc_nominated_individual": "Dr Bassel Hamameeh Al Wattar",
            "cqc_match_confidence": "name_website",
            "status": "unknown",
            "contact_email": "",
            "phone": "",
            "doctify_about": "",
        }
    )
    assert payload["cqc_location_id"] == "1-19271937885"
    assert payload["cqc_match_confidence"] == 0.92
    assert payload["visible_clinic_size"] == "micro"
    assert payload["postcode"] == "W1G 9PB"
    assert "Gynaecology" in payload["specialties"]
    assert payload["founder_score"] >= 20
