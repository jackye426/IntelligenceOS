"""RocketReach client unit tests (noop mode)."""

from gtm_pipeline.rocketreach.client import _pick_best_email, lookup_person


def test_rocketreach_noop(monkeypatch):
    monkeypatch.setenv("GTM_ROCKETREACH_MODE", "noop")
    out = lookup_person("Jane Doe", current_employer="Clinic")
    assert out["status"] == "skipped"


def test_pick_best_email_prefers_professional():
    email, conf = _pick_best_email(
        [
            {"email": "p@gmail.com", "type": "personal", "grade": "A", "smtp_valid": "valid"},
            {"email": "j@clinic.com", "type": "professional", "grade": "A", "smtp_valid": "valid"},
        ]
    )
    assert email == "j@clinic.com"
    assert conf >= 0.7


def test_pick_best_email_skips_invalid_smtp():
    email, conf = _pick_best_email(
        [
            {"email": "bad@clinic.com", "type": "professional", "grade": "A", "smtp_valid": "invalid"},
            {"email": "ok@gmail.com", "type": "personal", "grade": "A", "smtp_valid": "valid"},
        ]
    )
    assert email == "ok@gmail.com"


def test_clean_name():
    from gtm_pipeline.rocketreach.client import _clean_person_name

    assert _clean_person_name("Dr. Mohamed Abdelghani") == "Mohamed Abdelghani"
    assert _clean_person_name("Miss Clair Rosemary Linnane") == "Clair Rosemary Linnane"
