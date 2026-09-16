"""Unit tests for match-review banding (no network)."""

from gtm_pipeline import config
from gtm_pipeline.sync.match_reviews import maybe_queue_match_review


def test_auto_accept_skips_queue():
    out = maybe_queue_match_review(
        entity_type="clinic_cqc",
        candidate={"name": "A"},
        target={"name": "A"},
        confidence=config.MATCH_AUTO_ACCEPT,
        reasons=["test"],
        dry_run=True,
    )
    assert out is None


def test_below_review_skips_queue():
    out = maybe_queue_match_review(
        entity_type="clinic_cqc",
        candidate={"name": "A"},
        target={"name": "A"},
        confidence=max(0.0, config.MATCH_REVIEW_THRESHOLD - 0.01),
        reasons=["test"],
        dry_run=True,
    )
    assert out is None


def test_force_review_queues_even_above_auto_accept():
    out = maybe_queue_match_review(
        entity_type="creator_clinic",
        candidate={"name": "A"},
        target={"name": "B"},
        confidence=0.90,
        reasons=["bio_domain_overlap"],
        dedupe_key="creator_clinic:p1",
        dry_run=True,
        force_review=True,
    )
    assert out is not None
    assert out["dedupe_key"] == "creator_clinic:p1"
    assert out["status"] == "pending"
