"""
Stores and retrieves (consultantGUID, locationGUID) pairs discovered during booking flow
navigation. Seeded automatically from source_url values already in appointment_slots.

On the first run for a new consultant the browser-based scraper fires and records
GetLDBConsultantSlots URLs in source_url. On every subsequent run, populate_from_slots()
extracts those GUIDs so the direct API scraper can skip UI navigation entirely.
"""

import logging
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import AppointmentSlot, BookingGuid

logger = logging.getLogger(__name__)


def populate_from_slots(session: Session) -> int:
    """
    Scan source_url values in appointment_slots, extract GUIDs, upsert into booking_guids.
    Safe to call on every startup. Returns the number of new rows inserted.
    """
    rows = session.execute(
        select(
            AppointmentSlot.consultant_id,
            AppointmentSlot.location_name,
            AppointmentSlot.funding_route,
            AppointmentSlot.source_url,
        ).where(AppointmentSlot.source_url.contains("GetLDBConsultantSlots"))
    ).all()

    inserted = 0
    seen: set[tuple] = set()

    for consultant_id, location_name, funding_route, source_url in rows:
        key = (consultant_id, location_name, funding_route)
        if key in seen:
            continue
        seen.add(key)

        parsed = urlparse(source_url)
        params = parse_qs(parsed.query)
        consultant_guid = params.get("consultantGUID", [None])[0]
        location_guid = params.get("locationGUID", [None])[0]
        if not consultant_guid or not location_guid:
            continue

        existing = session.execute(
            select(BookingGuid).where(
                BookingGuid.consultant_id == consultant_id,
                BookingGuid.location_name == location_name,
                BookingGuid.funding_route == funding_route,
            )
        ).scalar_one_or_none()

        if existing:
            existing.consultant_guid = consultant_guid
            existing.location_guid = location_guid
        else:
            session.add(BookingGuid(
                consultant_id=consultant_id,
                location_name=location_name,
                funding_route=funding_route,
                consultant_guid=consultant_guid,
                location_guid=location_guid,
            ))
            inserted += 1

    session.commit()
    if inserted:
        logger.info("guid_store: %d new GUID entries stored", inserted)
    return inserted


def get_guids_for_consultant(session: Session, consultant_id: int) -> list[BookingGuid]:
    """Return all stored BookingGuid rows for a consultant."""
    return session.execute(
        select(BookingGuid).where(BookingGuid.consultant_id == consultant_id)
    ).scalars().all()
