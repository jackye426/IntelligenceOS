"""Tests for CQC name-only / website fallback (Clinic sales agent matcher)."""

from __future__ import annotations

import pandas as pd
import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Clinic sales agent" / "src"))

import cqc_lookup as cqc  # noqa: E402


@pytest.fixture()
def tiny_dir(monkeypatch):
    df = pd.DataFrame(
        [
            {
                "Name": "The Luna Clinic",
                "Postcode": "SE1 9RS",
                "Address": "Keats House, London",
                "Phone number": "02000000000",
                "Service's website (if available)": "https://thelunaclinic.com/",
                "Location URL": "https://www.cqc.org.uk/location/1-luna",
                "CQC Location ID (for office use only)": "1-luna",
                "Provider name": "Luna Ltd",
                "Specialisms/services": "",
            },
            {
                "Name": "Queen's Hospital",
                "Postcode": "RM7 0AG",
                "Address": "Romford",
                "Phone number": "",
                "Service's website (if available)": "",
                "Location URL": "https://www.cqc.org.uk/location/1-qh",
                "CQC Location ID (for office use only)": "1-qh",
                "Provider name": "BHRUT",
                "Specialisms/services": "",
            },
            {
                "Name": "The Mole Clinic",
                "Postcode": "W1B 1LU",
                "Address": "London",
                "Phone number": "",
                "Service's website (if available)": "https://themoleclinic.co.uk/",
                "Location URL": "https://www.cqc.org.uk/location/1-mole",
                "CQC Location ID (for office use only)": "1-mole",
                "Provider name": "Mole Ltd",
                "Specialisms/services": "",
            },
            {
                "Name": "Some Other Clinic",
                "Postcode": "W1G 9PB",
                "Address": "Harley Street",
                "Phone number": "",
                "Service's website (if available)": "",
                "Location URL": "https://www.cqc.org.uk/location/1-other",
                "CQC Location ID (for office use only)": "1-other",
                "Provider name": "Other",
                "Specialisms/services": "",
            },
        ]
    )
    df["_name_lower"] = df["Name"].str.lower().str.strip()
    df["_web_domain"] = df["Service's website (if available)"].map(cqc._website_domain)
    monkeypatch.setattr(cqc, "_DIR_CACHE", df)
    monkeypatch.setattr(cqc, "_WEB_INDEX", None)
    return df


def test_name_only_recovers_when_postcode_differs(tiny_dir):
    row, method = cqc._find_in_directory(
        "The Luna Clinic",
        "London, W1G 9PB",  # Doctify postcode ≠ CQC SE1
    )
    assert row is not None
    assert row["Name"] == "The Luna Clinic"
    assert method == "name_only"


def test_website_recovers_branch_brand(tiny_dir):
    row, method = cqc._find_in_directory(
        "The Mole Clinic Oxford Circus",
        "London, W1B 1LU",
        website="https://themoleclinic.co.uk/london-oxfordcircus/",
    )
    assert row is not None
    assert row["Name"] == "The Mole Clinic"
    assert method in {"website", "name_website", "geo"}


def test_single_token_queen_does_not_collide(tiny_dir):
    row, method = cqc._find_in_directory("Queen's Clinic", "London, W1G 9RT")
    # Must not jump to Queen's Hospital via global name-only
    assert row is None or row["Name"] != "Queen's Hospital"


def test_geo_still_preferred_when_postcode_matches(tiny_dir):
    row, method = cqc._find_in_directory("Some Other Clinic", "London, W1G 9PB")
    assert row is not None
    assert row["Name"] == "Some Other Clinic"
    assert method == "geo"
