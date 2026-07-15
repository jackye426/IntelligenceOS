"""Specialty normaliser unit tests (no network)."""

from gtm_pipeline.segments.specialty import (
    clinic_specialty_keys,
    primary_specialty_label,
    specialty_to_keys,
    tags_to_keys,
)


def test_og_aliases():
    assert "obstetrics_gynaecology" in specialty_to_keys("Obstetrics & Gynaecology")
    assert "obstetrics_gynaecology" in specialty_to_keys("Gynecology")


def test_fertility_and_menopause():
    keys = tags_to_keys(["IVF & fertility", "Menopause clinic"])
    assert "fertility" in keys
    assert "ivf" in keys
    assert "menopause" in keys


def test_clinic_specialty_keys_merges_sources():
    keys = clinic_specialty_keys(
        ["Dermatology"],
        ["Mental health"],
        ["Endometriosis specialist"],
    )
    assert "dermatology" in keys
    assert "mental_health" in keys
    assert "endometriosis" in keys


def test_primary_prefers_preferred_keys():
    label = primary_specialty_label(
        ["Cardiology", "Fertility"],
        preferred_keys={"fertility", "ivf"},
    )
    assert label == "Fertility"
