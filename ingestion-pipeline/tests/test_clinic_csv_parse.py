"""Clinic sales CSV -> staging envelope mapping."""

import csv
from pathlib import Path

from ingestion_pipeline.lanes.clinic_csv.parse import parse_clinic_csv

COLUMNS = [
    "clinic_name", "doctify_profile_url", "website_url", "location",
    "specialty_tags", "specialist_count", "review_count", "contact_email",
    "phone", "doctify_about", "cqc_registered_manager", "status", "filter_reason",
]

ROWS = [
    {
        "clinic_name": "Example Gynaecology",
        "doctify_profile_url": "https://www.doctify.com/uk/practice/example",
        "website_url": "https://example-gyn.co.uk/",
        "location": "London, W1G 1AA",
        "specialty_tags": "Gynaecology; Fertility Medicine",
        "contact_email": "info@example-gyn.co.uk",
        "cqc_registered_manager": "Dr Jane Doe",
        "status": "unknown",
    },
    {
        # No website: Doctify URL must be used to satisfy NOT NULL website_url.
        "clinic_name": "No Website Clinic",
        "doctify_profile_url": "https://www.doctify.com/uk/practice/no-website",
        "status": "unknown",
    },
    {
        "clinic_name": "Big NHS Hospital",
        "doctify_profile_url": "https://www.doctify.com/uk/practice/nhs",
        "status": "pre_filtered",
        "filter_reason": 'hospital/NHS: "nhs trust"',
    },
]


def _write_csv(path: Path) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in ROWS:
            writer.writerow({c: row.get(c, "") for c in COLUMNS})
    return path


def test_parse_skips_prefiltered_and_falls_back_to_doctify_url(tmp_path):
    records = parse_clinic_csv(_write_csv(tmp_path / "sales.csv"))

    assert [r.source_title for r in records] == ["Example Gynaecology", "No Website Clinic"]
    assert records[0].source_url == "https://example-gyn.co.uk/"
    assert records[1].source_url == "https://www.doctify.com/uk/practice/no-website"

    contacts = records[0].metadata["contacts"]
    assert {c["role"] for c in contacts} == {"Registered Manager (CQC)", "General enquiries"}
    assert "Gynaecology" in records[0].embed_text


def test_parse_include_filtered_and_limit(tmp_path):
    path = _write_csv(tmp_path / "sales.csv")
    assert len(parse_clinic_csv(path, include_filtered=True)) == 3
    assert len(parse_clinic_csv(path, limit=1)) == 1
