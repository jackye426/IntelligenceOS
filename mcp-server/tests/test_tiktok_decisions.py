"""Unit tests for TikTok decision log helpers (no live Supabase)."""

from __future__ import annotations

from datetime import date

from tools.tiktok_decisions import compact_decisions_for_brief, is_due


def test_is_due_open_past_review_after():
    d = {"status": "committed", "review_after": "2026-07-01"}
    assert is_due(d, today=date(2026, 7, 10)) is True


def test_is_due_open_future_review_after():
    d = {"status": "committed", "review_after": "2026-07-20"}
    assert is_due(d, today=date(2026, 7, 10)) is False


def test_is_due_closed_never():
    d = {"status": "outcome_recorded", "review_after": "2026-07-01"}
    assert is_due(d, today=date(2026, 7, 10)) is False


def test_compact_decisions_for_brief_splits_open_and_closed():
    decisions = [
        {
            "decision_id": "open-1",
            "status": "committed",
            "decision": "Repost with CTA",
            "review_after": "2026-07-15",
            "platform": "tiktok",
        },
        {
            "decision_id": "closed-1",
            "status": "outcome_recorded",
            "decision": "Kill soft open",
            "closed_at": "2026-07-09T00:00:00+00:00",
            "outcome": {"verdict": "confirmed"},
            "implication": "avoid",
            "platform": "tiktok",
        },
        {
            "decision_id": "cancelled-1",
            "status": "cancelled",
            "decision": "Hold filming",
            "closed_at": "2026-07-08T00:00:00+00:00",
            "platform": "tiktok",
        },
    ]
    compact = compact_decisions_for_brief(decisions)
    assert compact["open_count"] == 1
    assert compact["closed_count"] == 2
    assert compact["open"][0]["decision_id"] == "open-1"
    assert compact["recent_closed"][0]["decision_id"] == "closed-1"
