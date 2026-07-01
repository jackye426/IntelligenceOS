"""
Tests for storage/slot_lifecycle.py

Covers all four lifecycle state transitions:
1. New slot insertion
2. Seen-again update (last_seen_at + times_seen_count)
3. Disappeared: previously visible future slot absent on new scrape
4. Expired_visible: slot within T-48h window still visible on previous scrape
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from db.models import AppointmentSlot
from storage.slot_lifecycle import upsert_slots
from tests.conftest import dt_eq, future_dt, make_slot


def _get_slot(session: Session, consultant_id: int, slot_dt: datetime) -> AppointmentSlot | None:
    # SQLite stores datetimes as naive strings; strip tzinfo from query value to match
    dt_naive = slot_dt.replace(tzinfo=None)
    return (
        session.query(AppointmentSlot)
        .filter(
            AppointmentSlot.consultant_id == consultant_id,
            AppointmentSlot.slot_datetime == dt_naive,
        )
        .first()
    )


class TestInsertNewSlot:
    def test_new_slot_inserted(self, db_session, sample_consultant):
        cid = sample_consultant
        now = datetime.now(timezone.utc)
        dt = future_dt(10)
        slots = [make_slot(cid, dt)]

        upsert_slots(db_session, slots, scrape_run_id=1, collection_ts=now)

        row = _get_slot(db_session, cid, dt)
        assert row is not None
        assert row.current_status == "visible"
        assert row.times_seen_count == 1
        assert dt_eq(row.first_seen_at, now)
        assert dt_eq(row.last_seen_at, now)

    def test_multiple_new_slots_all_inserted(self, db_session, sample_consultant):
        cid = sample_consultant
        now = datetime.now(timezone.utc)
        dts = [future_dt(d) for d in [5, 10, 20, 30]]
        slots = [make_slot(cid, dt) for dt in dts]

        result = upsert_slots(db_session, slots, scrape_run_id=1, collection_ts=now)

        assert result["inserted"] == 4
        assert result["updated"] == 0


class TestSeenAgainUpdate:
    def test_seen_again_increments_count(self, db_session, sample_consultant):
        cid = sample_consultant
        now = datetime.now(timezone.utc)
        dt = future_dt(15)
        slots = [make_slot(cid, dt)]

        # First scrape
        upsert_slots(db_session, slots, scrape_run_id=1, collection_ts=now)
        # Second scrape
        second_ts = now + timedelta(hours=8)
        result = upsert_slots(db_session, slots, scrape_run_id=2, collection_ts=second_ts)

        row = _get_slot(db_session, cid, dt)
        assert result["updated"] == 1
        assert result["inserted"] == 0
        assert row.times_seen_count == 2
        assert dt_eq(row.last_seen_at, second_ts)
        assert row.current_status == "visible"

    def test_first_seen_not_overwritten(self, db_session, sample_consultant):
        cid = sample_consultant
        first_ts = datetime.now(timezone.utc)
        dt = future_dt(15)
        slots = [make_slot(cid, dt)]

        upsert_slots(db_session, slots, scrape_run_id=1, collection_ts=first_ts)
        later_ts = first_ts + timedelta(hours=12)
        upsert_slots(db_session, slots, scrape_run_id=2, collection_ts=later_ts)

        row = _get_slot(db_session, cid, dt)
        assert dt_eq(row.first_seen_at, first_ts)  # unchanged


class TestDisappeared:
    def test_absent_future_slot_marked_disappeared(self, db_session, sample_consultant):
        cid = sample_consultant
        first_ts = datetime.now(timezone.utc)
        dt = future_dt(10)
        slots = [make_slot(cid, dt)]

        # First scrape: slot visible
        upsert_slots(db_session, slots, scrape_run_id=1, collection_ts=first_ts)

        # Second scrape: slot absent (pass different slot)
        second_ts = first_ts + timedelta(hours=8)
        different_slot = make_slot(cid, future_dt(15))
        result = upsert_slots(db_session, [different_slot], scrape_run_id=2, collection_ts=second_ts)

        row = _get_slot(db_session, cid, dt)
        assert row.current_status == "disappeared"
        assert result["disappeared"] == 1

    def test_slot_within_48h_not_marked_disappeared(self, db_session, sample_consultant):
        """A slot inside the T-48h window should become expired_visible, not disappeared."""
        cid = sample_consultant
        first_ts = datetime.now(timezone.utc)
        # Slot is 30 hours in the future — inside T-48h
        dt = first_ts + timedelta(hours=30)
        slots = [make_slot(cid, dt)]

        upsert_slots(db_session, slots, scrape_run_id=1, collection_ts=first_ts)

        # Second scrape: slot absent
        second_ts = first_ts + timedelta(hours=8)
        different = make_slot(cid, future_dt(20))
        upsert_slots(db_session, [different], scrape_run_id=2, collection_ts=second_ts)

        row = _get_slot(db_session, cid, dt)
        assert row.current_status == "expired_visible"


class TestExpiredVisible:
    def test_visible_slot_in_48h_window_marked_expired(self, db_session, sample_consultant):
        cid = sample_consultant
        first_ts = datetime.now(timezone.utc)
        # Slot is 30 hours out — within T-48h
        dt = first_ts + timedelta(hours=30)
        slots = [make_slot(cid, dt)]

        upsert_slots(db_session, slots, scrape_run_id=1, collection_ts=first_ts)

        # Second scrape: only a far-future slot returned — T+30h slot is absent.
        # upsert_slots needs a non-empty list to determine the group key.
        second_ts = first_ts + timedelta(hours=2)
        far_future = make_slot(cid, future_dt(20))
        upsert_slots(db_session, [far_future], scrape_run_id=2, collection_ts=second_ts)

        row = _get_slot(db_session, cid, dt)
        # T+30h is within t48h_boundary (second_ts + 48h = first_ts + 50h), so: expired_visible
        assert row.current_status == "expired_visible"

    def test_no_duplicate_rows(self, db_session, sample_consultant):
        """Running upsert twice must not create duplicate rows."""
        cid = sample_consultant
        now = datetime.now(timezone.utc)
        dt = future_dt(7)
        slots = [make_slot(cid, dt)]

        upsert_slots(db_session, slots, scrape_run_id=1, collection_ts=now)
        upsert_slots(db_session, slots, scrape_run_id=2, collection_ts=now + timedelta(hours=8))

        # Query with naive dt to match SQLite storage
        count = (
            db_session.query(AppointmentSlot)
            .filter(
                AppointmentSlot.consultant_id == cid,
                AppointmentSlot.slot_datetime == dt.replace(tzinfo=None),
            )
            .count()
        )
        assert count == 1
