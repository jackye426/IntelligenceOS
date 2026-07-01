"""Reusable pandas query helpers over the appointment_slots table."""

import pandas as pd
from sqlalchemy.orm import Session

from db.models import AppointmentSlot


def load_slots_df(
    session: Session,
    consultant_id: int | None = None,
    location_name: str | None = None,
    funding_route: str | None = None,
) -> pd.DataFrame:
    """
    Load appointment_slots into a DataFrame, optionally filtered.

    Each row is one unique physical slot time. Appointment-type compatibility
    is represented by the available_for_initial and available_for_follow_up columns.
    """
    from sqlalchemy import select
    q = select(AppointmentSlot)
    if consultant_id is not None:
        q = q.where(AppointmentSlot.consultant_id == consultant_id)
    if location_name is not None:
        q = q.where(AppointmentSlot.location_name == location_name)
    if funding_route is not None:
        q = q.where(AppointmentSlot.funding_route == funding_route)

    rows = session.execute(q).scalars().all()
    if not rows:
        return pd.DataFrame()

    records = [
        {
            "slot_id": r.slot_id,
            "consultant_id": r.consultant_id,
            "consultant_name": r.consultant_name,
            "location_name": r.location_name,
            "funding_route": r.funding_route,
            "slot_datetime": r.slot_datetime,
            "slot_date": r.slot_date,
            "slot_time": r.slot_time,
            "available_for_initial": r.available_for_initial,
            "available_for_follow_up": r.available_for_follow_up,
            "price": r.price,
            "first_seen_at": r.first_seen_at,
            "last_seen_at": r.last_seen_at,
            "times_seen_count": r.times_seen_count,
            "current_status": r.current_status,
        }
        for r in rows
    ]
    df = pd.DataFrame(records)
    # SQLite stores datetimes as naive strings; treat all as UTC
    for col in ("slot_datetime", "first_seen_at", "last_seen_at"):
        df[col] = pd.to_datetime(df[col]).dt.tz_localize("UTC", nonexistent="NaT", ambiguous="NaT")
    return df
