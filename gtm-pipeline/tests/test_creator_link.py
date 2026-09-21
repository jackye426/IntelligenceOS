"""Creator identity linking: method precedence, ambiguity, DNC, recheck."""

from __future__ import annotations

from gtm_pipeline.creators.exports import export_practitioner_seeds, export_specialty_map
from gtm_pipeline.creators.link import (
    IdentityIndexes,
    build_indexes,
    host_of,
    link_creators,
    match_profile,
    recheck_duplicate_clinics,
)
from gtm_pipeline.shared.name import person_name_key


def _indexes(**kwargs) -> IdentityIndexes:
    return build_indexes(
        practitioners=kwargs.get("practitioners") or [],
        people=kwargs.get("people") or [],
        clinics=kwargs.get("clinics") or [],
        outreach=kwargs.get("outreach") or [],
    )


def _profile(**extra):
    row = {
        "id": "p1",
        "handle": "drjane",
        "nickname": "Dr Jane Smith",
        "geo_country": "GB",
        "lane": "customer",
        "specialty_key": "colorectal",
        "bio_emails": [],
        "bio_links": [],
        "gmc_number_in_bio": None,
        "do_not_contact": False,
    }
    row.update(extra)
    return row


def test_host_of_strips_www():
    assert host_of("https://www.Jane.clinic/about") == "jane.clinic"


def test_gmc_in_bio_confirmed_unique():
    indexes = _indexes(
        practitioners=[{"id": "prac-1", "name": "Jane Smith", "gmc_number": "1234567"}]
    )
    hits = match_profile(_profile(gmc_number_in_bio="1234567"), indexes)
    assert len(hits) == 1
    assert hits[0].method == "gmc_in_bio"
    assert hits[0].confidence == 0.99
    assert hits[0].status == "confirmed"


def test_ambiguous_top_confidence_stays_suggested():
    indexes = _indexes(
        practitioners=[
            {"id": "prac-1", "name": "Jane Smith", "gmc_number": "1234567"},
            {"id": "prac-2", "name": "Jane Smyth", "gmc_number": "1234567"},
        ]
    )
    hits = match_profile(_profile(gmc_number_in_bio="1234567"), indexes)
    assert len(hits) == 2
    assert {h.status for h in hits} == {"suggested"}


def test_email_exact_and_bio_domain():
    indexes = _indexes(
        practitioners=[{"id": "prac-1", "name": "Jane", "email": "jane@clinic.co.uk"}],
        clinics=[{"id": "cl-1", "clinic_name": "Jane Clinic", "website_url": "https://jane.clinic"}],
    )
    profile = _profile(
        bio_emails=["jane@clinic.co.uk"],
        bio_links=[{"url": "https://jane.clinic", "class": "own_site"}],
    )
    hits = match_profile(profile, indexes)
    methods = {h.method: h for h in hits}
    assert methods["email_exact"].status == "confirmed"
    assert methods["email_exact"].confidence == 0.95
    assert methods["bio_domain"].status == "suggested"
    assert methods["bio_domain"].target_table == "gtm_clinic_intelligence"


def test_name_specialty_vs_name_only():
    indexes = _indexes(
        practitioners=[
            {
                "id": "prac-1",
                "name": "Dr Jane Smith",
                "specialty": "Colorectal surgery",
            },
            {"id": "prac-2", "name": "Dr Jane Smith", "specialty": "Dermatology"},
        ]
    )
    hits = match_profile(_profile(nickname="Jane Smith"), indexes)
    by_id = {h.target_id: h for h in hits}
    assert by_id["prac-1"].method == "name_specialty"
    assert by_id["prac-1"].confidence == 0.75
    assert by_id["prac-2"].method == "name_only"
    assert by_id["prac-2"].confidence == 0.50
    assert by_id["prac-2"].status == "suggested"


def test_person_name_key_aligns():
    assert person_name_key("Dr Jane Smith") == person_name_key("Jane Smith")


def test_dnc_from_doctor_outreach():
    indexes = _indexes(
        practitioners=[{"id": "prac-1", "name": "Jane", "gmc_number": "1234567"}],
        outreach=[{"practitioner_id": "prac-1", "status": "dnc"}],
    )
    profile = _profile(gmc_number_in_bio="1234567")
    out = link_creators(
        profiles=[profile],
        indexes=indexes,
        dry_run=True,
        client=None,
    )
    assert out["do_not_contact"] == 1
    assert profile["do_not_contact"] is True
    methods = {row["target_table"] for row in out["profiles"][0]["links"]}
    assert "doctor_outreach" in methods


def test_recheck_queues_force_review(monkeypatch):
    queued = []

    def fake_queue(**kwargs):
        queued.append(kwargs)
        return {"dedupe_key": kwargs["dedupe_key"], "status": "pending"}

    monkeypatch.setattr("gtm_pipeline.creators.link.maybe_queue_match_review", fake_queue)
    indexes = _indexes(
        clinics=[
            {
                "id": "cl-creator",
                "clinic_name": "Jane PP",
                "website_url": "https://jane.clinic",
                "source_creator_profile_id": "p1",
                "doctify_url": None,
            },
            {
                "id": "cl-doctify",
                "clinic_name": "Jane Doctify",
                "website_url": "https://jane.clinic",
                "source_creator_profile_id": None,
                "doctify_url": "https://www.doctify.com/uk/practice/jane",
            },
        ]
    )
    reviews = recheck_duplicate_clinics(indexes=indexes, dry_run=True)
    assert reviews
    assert queued[0]["force_review"] is True
    assert queued[0]["dedupe_key"] == "creator_clinic:p1"
    assert queued[0]["confidence"] == 0.90


def test_export_practitioner_seeds_from_memory(tmp_path):
    path = tmp_path / "seeds.csv"
    out = export_practitioner_seeds(
        specialties=["colorectal"],
        limit=10,
        path=path,
        practitioners=[
            {
                "id": "a",
                "name": "Jane Smith",
                "specialty": "Colorectal surgery",
                "gmc_number": "1234567",
            },
            {"id": "b", "name": "Someone Else", "specialty": "Cardiology", "gmc_number": ""},
        ],
    )
    assert out["count"] == 1
    text = path.read_text()
    assert "Jane Smith" in text
    assert "practitioner" in text
    assert "1234567" in text


def test_export_specialty_map_includes_colorectal(tmp_path):
    path = tmp_path / "keys.json"
    out = export_specialty_map(path)
    assert "colorectal" in out["keys"]
    assert path.exists()
