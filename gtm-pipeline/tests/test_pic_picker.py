"""PIC picker unit tests (no network)."""

from gtm_pipeline.contacts.pic import (
    derive_preferred_channel,
    pick_person_in_charge,
    synthetic_pic_from_cqc,
)


def test_pic_prefers_ni_over_specialist_with_email():
    people = [
        {
            "id": "1",
            "full_name": "Specialist With Email",
            "role": "specialist",
            "email": "s@example.com",
            "priority": 99,
        },
        {
            "id": "2",
            "full_name": "NI Person",
            "role": "nominated_individual",
            "email": None,
            "priority": 50,
        },
    ]
    pic = pick_person_in_charge(people)
    assert pic["id"] == "2"


def test_pic_rm_when_no_ni():
    people = [
        {"id": "1", "full_name": "RM", "role": "registered_manager", "email": None, "priority": 50},
        {"id": "2", "full_name": "Spec", "role": "specialist", "email": "a@b.c", "priority": 90},
    ]
    assert pick_person_in_charge(people)["id"] == "1"


def test_synthetic_from_cqc():
    syn = synthetic_pic_from_cqc(
        cqc_nominated_individual="Dr Jane Doe",
        cqc_registered_manager="Other",
    )
    assert syn["role"] == "nominated_individual"
    assert syn["full_name"] == "Dr Jane Doe"


def test_preferred_channel():
    assert derive_preferred_channel(email="a@b.c", linkedin_url="https://linkedin.com/in/x") == "email"
    assert derive_preferred_channel(email="", linkedin_url="https://linkedin.com/in/x") == "linkedin"
    assert derive_preferred_channel(email="", linkedin_url="") == "none"
