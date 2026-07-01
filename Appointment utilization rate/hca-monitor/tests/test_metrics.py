"""Tests for analysis/metrics.py — requires at least synthetic scrape data."""

from datetime import datetime, timedelta, timezone

import pytest

from analysis.metrics import compute_decay_metrics
from storage.slot_lifecycle import upsert_slots
from tests.conftest import future_dt, make_slot


class TestDecayMetrics:
    def test_empty_db_returns_zeroes(self, db_session, sample_consultant):
        cid = sample_consultant
        m = compute_decay_metrics(db_session, cid, "The Lister Hospital", "initial", "self-pay")
        assert m.total_unique_slots_observed == 0
        assert m.max_visible_slots_30d == 0
        assert m.earliest_available_slot is None

    def test_visible_slots_counted_in_windows(self, db_session, sample_consultant):
        cid = sample_consultant
        now = datetime.now(timezone.utc)

        # Create slots at various distances
        # Use 1 day for T-2d window to stay safely within 48h (not on boundary)
        slots = [
            make_slot(cid, future_dt(1)),   # T-2d (within T-2 and all larger windows)
            make_slot(cid, future_dt(4)),   # T-7 window
            make_slot(cid, future_dt(10)),  # T-14 window
            make_slot(cid, future_dt(20)),  # T-21 window
            make_slot(cid, future_dt(25)),  # T-30d
        ]
        upsert_slots(db_session, slots, scrape_run_id=1, collection_ts=now)

        m = compute_decay_metrics(
            db_session, cid, "The Lister Hospital", "initial", "self-pay",
            reference_dt=now,
        )

        # T-2 window (48h): only the first slot (1 day away)
        assert m.slots_within_t_windows[2] == 1
        # T-7 window: first two slots
        assert m.slots_within_t_windows[7] == 2
        # T-14 window: first three
        assert m.slots_within_t_windows[14] == 3
        # T-21 window: first four
        assert m.slots_within_t_windows[21] == 4

    def test_total_unique_slots_observed(self, db_session, sample_consultant):
        cid = sample_consultant
        now = datetime.now(timezone.utc)
        slots = [make_slot(cid, future_dt(d)) for d in [5, 10, 15, 20]]
        upsert_slots(db_session, slots, scrape_run_id=1, collection_ts=now)

        m = compute_decay_metrics(db_session, cid, "The Lister Hospital", "initial", "self-pay")
        assert m.total_unique_slots_observed == 4

    def test_pct_visible_none_when_insufficient_history(self, db_session, sample_consultant):
        cid = sample_consultant
        now = datetime.now(timezone.utc)
        slots = [make_slot(cid, future_dt(10))]
        upsert_slots(db_session, slots, scrape_run_id=1, collection_ts=now)

        m = compute_decay_metrics(db_session, cid, "The Lister Hospital", "initial", "self-pay")
        # Only 1 scrape — insufficient
        for days in [21, 14, 7, 3, 2]:
            assert m.pct_visible_at_t_windows[days] is None

    def test_earliest_and_furthest_slots(self, db_session, sample_consultant):
        cid = sample_consultant
        now = datetime.now(timezone.utc)
        dt_near = future_dt(5)
        dt_far = future_dt(45)
        upsert_slots(db_session, [make_slot(cid, dt_near), make_slot(cid, dt_far)],
                     scrape_run_id=1, collection_ts=now)

        m = compute_decay_metrics(db_session, cid, "The Lister Hospital", "initial", "self-pay",
                                  reference_dt=now)
        assert abs((m.earliest_available_slot - dt_near).total_seconds()) < 1
        assert abs((m.furthest_available_slot - dt_far).total_seconds()) < 1
