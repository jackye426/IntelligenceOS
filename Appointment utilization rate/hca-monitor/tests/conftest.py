"""
Pytest fixtures for the HCA monitor test suite.

Key fixtures:
- db_session: in-memory SQLite session, schema created fresh per test
- make_slot: factory for creating SlotRecord test instances
- make_consultant: factory for inserting a Consultant row
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Add project root to sys.path so imports work without package install
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.models import Base, Consultant, ConsultantLocation
from scraper.slot_extractor import SlotRecord


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def sample_consultant(db_session: Session) -> int:
    """Insert a sample consultant and return its consultant_id."""
    c = Consultant(
        name="Michael Adamczyk",
        profile_url="https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/michael-adamczyk",
        specialty="Gynaecology",
        gmc_number="1234567",
    )
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)

    loc = ConsultantLocation(
        consultant_id=c.consultant_id,
        location_name="The Lister Hospital",
        published_days='["Thursday", "Friday", "Saturday"]',
        published_hours="Thursday 8am-5pm, Friday 1pm-7pm, Saturday 8am-7pm",
        is_available_on_profile=True,
    )
    db_session.add(loc)
    db_session.commit()
    return c.consultant_id


def make_slot(
    consultant_id: int,
    slot_datetime: datetime,
    location_name: str = "The Lister Hospital",
    appointment_type: str = "initial",
    funding_route: str = "self-pay",
    price: str | None = "£250",
) -> SlotRecord:
    slot_dt_london = slot_datetime.astimezone()  # display in local time
    return SlotRecord(
        consultant_id=consultant_id,
        consultant_name="Michael Adamczyk",
        profile_url="https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/michael-adamczyk",
        location_name=location_name,
        appointment_type=appointment_type,
        funding_route=funding_route,
        slot_datetime=slot_datetime,
        slot_date=slot_datetime.strftime("%Y-%m-%d"),
        slot_time=slot_datetime.strftime("%H:%M"),
        price=price,
    )


def future_dt(days: int) -> datetime:
    """Return a UTC datetime N days in the future."""
    return datetime.now(timezone.utc) + timedelta(days=days)


def dt_eq(a: datetime, b: datetime) -> bool:
    """Compare datetimes ignoring tzinfo — handles SQLite naive datetime round-trips."""
    return a.replace(tzinfo=None) == b.replace(tzinfo=None)
