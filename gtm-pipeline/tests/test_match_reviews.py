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


def test_ambiguous_queues_dry_run():
    mid = (config.MATCH_REVIEW_THRESHOLD + config.MATCH_AUTO_ACCEPT) / 2
    out = maybe_queue_match_review(
        entity_type="clinic_cqc",
        candidate={"name": "A"},
        target={"name": "B"},
        confidence=mid,
        reasons=["ambiguous"],
        dedupe_key="clinic_cqc:test:1",
        dry_run=True,
    )
    assert out is not None
    assert out["status"] == "pending"
    assert out["dedupe_key"] == "clinic_cqc:test:1"
