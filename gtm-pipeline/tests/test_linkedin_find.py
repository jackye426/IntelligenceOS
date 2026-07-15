"""LinkedIn search parsing / noop mode (no network when noop)."""

import os

from gtm_pipeline.linkedin.find import search_linkedin_profile_url


def test_linkedin_noop_mode(monkeypatch):
    monkeypatch.setenv("GTM_LINKEDIN_FIND_MODE", "noop")
    out = search_linkedin_profile_url("Jane Doe", clinic_name="Test Clinic")
    assert out["status"] == "skipped"
    assert out["linkedin_url"] == ""
