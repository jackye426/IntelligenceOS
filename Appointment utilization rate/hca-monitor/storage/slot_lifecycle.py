"""
Slot lifecycle upsert logic.

Each call handles one (consultant_id, location_name, funding_route) batch.
The batch may contain SlotRecords with appointment_type = 'initial' OR 'follow-up'
(or both) for the same slot_datetime — these are merged into a single DB row with
boolean flags: available_for_initial / available_for_follow_up.

Lifecycle rules per scrape:
1. Incoming slot_datetime present in DB  → update flags, last_seen_at, times_seen_count, status=visible
2. Incoming slot_datetime new            → INSERT with flags set, status=visible
3. DB slot_datetime absent from incoming AND slot_datetime > now+48h  → status='disappeared'
4. DB slot_datetime absent from incoming AND slot_datetime <= now+48h → status='expired_visible'
"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from db.models import AppointmentSlot, BookingSnapshot
from scraper.slot_extractor import SlotRecord

logger = logging.getLogger(__name__)

_T48H = timedelta(hours=48)


def upsert_slots(
    session: Session,
    slots: list[SlotRecord],
    scrape_run_id: int,
    collection_ts: datetime | None = None,
    page_url: str | None = None,
    screenshot_path: str | None = None,
    page_html: str | None = None,
) -> dict:
    """
    Persist slots for one (consultant_id, location_name, funding_route) batch.
    slots may contain records for both 'initial' and 'follow-up' appointment_types;
    they are merged into single rows keyed by slot_datetime.
    Returns summary counts.
    """
    if not slots:
        return {"inserted": 0, "updated": 0, "disappeared": 0, "expired_visible": 0}

    if collection_ts is None:
        collection_ts = datetime.now(timezone.utc)

    first = slots[0]
    consultant_id = first.consultant_id
    location_name = first.location_name
    funding_route = first.funding_route

    # BookingSnapshot: record which appointment types were present in this batch
    appt_types_present = ",".join(sorted(set(s.appointment_type for s in slots)))
    raw_html_hash = hashlib.sha256(page_html.encode()).hexdigest() if page_html else None
    snapshot = BookingSnapshot(
        scrape_run_id=scrape_run_id,
        consultant_id=consultant_id,
        location_name=location_name,
        appointment_type=appt_types_present,
        funding_route=funding_route,
        collection_timestamp=collection_ts,
        page_url=page_url,
        raw_html_hash=raw_html_hash,
        screenshot_path=screenshot_path,
        status="ok" if slots else "empty",
    )
    session.add(snapshot)

    # Normalise to naive UTC — SQLite stores datetimes without timezone info
    collection_ts_naive = collection_ts.replace(tzinfo=None)

    # Build incoming map: (consultant_id, location_name, funding_route, dt_naive)
    #   -> {available_for_initial, available_for_follow_up, representative SlotRecord}
    incoming: dict[tuple, dict] = {}
    for s in slots:
        dt = s.slot_datetime.replace(tzinfo=None) if s.slot_datetime.tzinfo else s.slot_datetime
        key = (s.consultant_id, s.location_name, s.funding_route, dt)
        if key not in incoming:
            incoming[key] = {
                "available_for_initial": False,
                "available_for_follow_up": False,
                "rec": s,
            }
        if s.appointment_type == "initial":
            incoming[key]["available_for_initial"] = True
        elif s.appointment_type == "follow-up":
            incoming[key]["available_for_follow_up"] = True

    # Query all known future slots for this (consultant, location, funding) group
    existing_rows = session.execute(
        select(AppointmentSlot).where(
            and_(
                AppointmentSlot.consultant_id == consultant_id,
                AppointmentSlot.location_name == location_name,
                AppointmentSlot.funding_route == funding_route,
                AppointmentSlot.slot_datetime > collection_ts_naive,
            )
        )
    ).scalars().all()

    existing: dict[tuple, AppointmentSlot] = {
        (r.consultant_id, r.location_name, r.funding_route, r.slot_datetime): r
        for r in existing_rows
    }

    inserted = updated = disappeared = expired_visible_count = 0

    # Upsert incoming slots
    for key, data in incoming.items():
        rec = data["rec"]
        if key in existing:
            row = existing[key]
            row.last_seen_at = collection_ts_naive
            row.times_seen_count += 1
            row.current_status = "visible"
            row.available_for_initial = data["available_for_initial"]
            row.available_for_follow_up = data["available_for_follow_up"]
            updated += 1
        else:
            dt_naive = key[3]
            session.add(AppointmentSlot(
                consultant_id=rec.consultant_id,
                consultant_name=rec.consultant_name,
                profile_url=rec.profile_url,
                location_name=rec.location_name,
                funding_route=rec.funding_route,
                slot_datetime=dt_naive,
                slot_date=rec.slot_date,
                slot_time=rec.slot_time,
                slot_timezone=rec.slot_timezone,
                available_for_initial=data["available_for_initial"],
                available_for_follow_up=data["available_for_follow_up"],
                price=rec.price,
                first_seen_at=collection_ts_naive,
                last_seen_at=collection_ts_naive,
                times_seen_count=1,
                current_status="visible",
                source_url=rec.source_url,
            ))
            inserted += 1

    # Mark disappeared / expired_visible for slots absent from this scrape
    t48h_boundary = collection_ts_naive + _T48H
    for key, row in existing.items():
        if key in incoming:
            continue
        if row.slot_datetime < t48h_boundary:
            if row.current_status == "visible":
                row.current_status = "expired_visible"
                expired_visible_count += 1
        else:
            if row.current_status == "visible":
                row.current_status = "disappeared"
                disappeared += 1

    session.commit()

    summary = {
        "inserted": inserted,
        "updated": updated,
        "disappeared": disappeared,
        "expired_visible": expired_visible_count,
    }
    logger.info(
        "Upsert %s/%s: +%d inserted, ~%d updated, -%d disappeared, ~%d expired_visible",
        location_name, funding_route,
        inserted, updated, disappeared, expired_visible_count,
    )
    return summary


def persist_consultant(session: Session, profile) -> int:
    """
    Upsert a Consultant row from a ConsultantProfile. Returns consultant_id.
    """
    import json as _json

    from db.models import Consultant, ConsultantLocation

    existing = session.execute(
        select(Consultant).where(Consultant.profile_url == profile.profile_url)
    ).scalar_one_or_none()

    if existing:
        existing.name = profile.name
        existing.specialty = profile.specialty
        existing.gmc_number = profile.gmc_number
        existing.review_count = profile.review_count
        existing.new_appointment_fee = profile.new_appointment_fee
        existing.follow_up_fee = profile.follow_up_fee
        session.commit()
        consultant_id = existing.consultant_id
    else:
        new_c = Consultant(
            name=profile.name,
            profile_url=profile.profile_url,
            specialty=profile.specialty,
            gmc_number=profile.gmc_number,
            review_count=profile.review_count,
            new_appointment_fee=profile.new_appointment_fee,
            follow_up_fee=profile.follow_up_fee,
        )
        session.add(new_c)
        session.commit()
        session.refresh(new_c)
        consultant_id = new_c.consultant_id

    for loc in profile.locations:
        existing_loc = session.execute(
            select(ConsultantLocation).where(
                and_(
                    ConsultantLocation.consultant_id == consultant_id,
                    ConsultantLocation.location_name == loc.location_name,
                )
            )
        ).scalar_one_or_none()

        if existing_loc:
            existing_loc.address = loc.address
            existing_loc.published_days = _json.dumps(loc.published_days)
            existing_loc.published_hours = loc.published_hours
            existing_loc.is_available_on_profile = loc.is_available_on_profile
        else:
            session.add(ConsultantLocation(
                consultant_id=consultant_id,
                location_name=loc.location_name,
                address=loc.address,
                published_days=_json.dumps(loc.published_days),
                published_hours=loc.published_hours,
                is_available_on_profile=loc.is_available_on_profile,
            ))

    session.commit()
    return consultant_id
