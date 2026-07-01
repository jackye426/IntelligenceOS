import json
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Consultant(Base):
    __tablename__ = "consultants"

    consultant_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_url: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    specialty: Mapped[str | None] = mapped_column(String(255))
    gmc_number: Mapped[str | None] = mapped_column(String(20))
    review_count: Mapped[int | None] = mapped_column(Integer)
    new_appointment_fee: Mapped[str | None] = mapped_column(String(100))
    follow_up_fee: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    locations: Mapped[list["ConsultantLocation"]] = relationship(back_populates="consultant", cascade="all, delete-orphan")
    slots: Mapped[list["AppointmentSlot"]] = relationship(back_populates="consultant", cascade="all, delete-orphan")


class ConsultantLocation(Base):
    __tablename__ = "consultant_locations"

    location_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    consultant_id: Mapped[int] = mapped_column(ForeignKey("consultants.consultant_id"), nullable=False)
    location_name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    published_days: Mapped[str | None] = mapped_column(Text)  # JSON list of day names
    published_hours: Mapped[str | None] = mapped_column(String(255))
    is_available_on_profile: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    consultant: Mapped["Consultant"] = relationship(back_populates="locations")

    __table_args__ = (UniqueConstraint("consultant_id", "location_name", name="uq_consultant_location"),)

    def get_published_days(self) -> list[str]:
        if not self.published_days:
            return []
        return json.loads(self.published_days)

    def set_published_days(self, days: list[str]) -> None:
        self.published_days = json.dumps(days)


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    scrape_run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")  # running / completed / error
    notes: Mapped[str | None] = mapped_column(Text)

    snapshots: Mapped[list["BookingSnapshot"]] = relationship(back_populates="scrape_run", cascade="all, delete-orphan")


class BookingSnapshot(Base):
    __tablename__ = "booking_snapshots"

    snapshot_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scrape_run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.scrape_run_id"), nullable=False)
    consultant_id: Mapped[int] = mapped_column(ForeignKey("consultants.consultant_id"), nullable=False)
    location_name: Mapped[str] = mapped_column(String(255), nullable=False)
    appointment_type: Mapped[str] = mapped_column(String(100), nullable=False)
    funding_route: Mapped[str] = mapped_column(String(100), nullable=False)
    collection_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    page_url: Mapped[str | None] = mapped_column(String(512))
    raw_html_hash: Mapped[str | None] = mapped_column(String(64))  # SHA-256 hex
    screenshot_path: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok / error / empty
    error_message: Mapped[str | None] = mapped_column(Text)

    scrape_run: Mapped["ScrapeRun"] = relationship(back_populates="snapshots")


class AppointmentSlot(Base):
    __tablename__ = "appointment_slots"

    slot_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    consultant_id: Mapped[int] = mapped_column(ForeignKey("consultants.consultant_id"), nullable=False)
    consultant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_url: Mapped[str] = mapped_column(String(512), nullable=False)
    location_name: Mapped[str] = mapped_column(String(255), nullable=False)
    funding_route: Mapped[str] = mapped_column(String(100), nullable=False)
    slot_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # UTC
    slot_date: Mapped[str] = mapped_column(String(10), nullable=False)   # YYYY-MM-DD display
    slot_time: Mapped[str] = mapped_column(String(8), nullable=False)    # HH:MM display
    slot_timezone: Mapped[str] = mapped_column(String(50), default="Europe/London")
    # Appointment-type compatibility flags — one physical slot may accept both types
    available_for_initial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    available_for_follow_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    price: Mapped[str | None] = mapped_column(String(100))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    times_seen_count: Mapped[int] = mapped_column(Integer, default=1)
    current_status: Mapped[str] = mapped_column(String(20), default="visible")
    source_url: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    consultant: Mapped["Consultant"] = relationship(back_populates="slots")

    __table_args__ = (
        UniqueConstraint(
            "consultant_id", "location_name", "funding_route", "slot_datetime",
            name="uq_slot_key",
        ),
    )


class BookingGuid(Base):
    """
    Stores the consultantGUID and locationGUID discovered during booking flow navigation.
    On subsequent runs the direct API scraper uses these to bypass UI navigation entirely.
    """
    __tablename__ = "booking_guids"

    guid_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    consultant_id: Mapped[int] = mapped_column(ForeignKey("consultants.consultant_id"), nullable=False)
    location_name: Mapped[str] = mapped_column(String(255), nullable=False)
    funding_route: Mapped[str] = mapped_column(String(100), nullable=False)
    consultant_guid: Mapped[str] = mapped_column(String(100), nullable=False)
    location_guid: Mapped[str] = mapped_column(String(100), nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        UniqueConstraint("consultant_id", "location_name", "funding_route", name="uq_booking_guid"),
    )
