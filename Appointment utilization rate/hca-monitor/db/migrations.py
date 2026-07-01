"""
Database schema management.

create_all()  — creates all tables on a fresh database.
migrate()     — upgrades an existing database in-place. Safe to call on every startup;
                detects which version is present and skips if already current.

Schema versions
  v1: appointment_slots has appointment_type column, unique key includes it
  v2: appointment_slots drops appointment_type; adds available_for_initial /
      available_for_follow_up booleans; unique key is (consultant_id, location_name,
      funding_route, slot_datetime).  Existing rows are merged during migration.
"""

import logging

from sqlalchemy import inspect, text

from db.engine import get_engine
from db.models import Base

logger = logging.getLogger(__name__)


def create_all() -> None:
    """Create all tables (no-op if they already exist)."""
    engine = get_engine()
    migrate(engine)           # apply any pending schema upgrades first
    Base.metadata.create_all(engine)  # create any tables that don't exist yet


def migrate(engine=None) -> None:
    """Apply incremental schema migrations. Safe to call on every startup."""
    if engine is None:
        engine = get_engine()

    inspector = inspect(engine)
    if "appointment_slots" not in inspector.get_table_names():
        logger.debug("appointment_slots does not exist yet — nothing to migrate")
        return

    columns = {c["name"] for c in inspector.get_columns("appointment_slots")}

    if "appointment_type" in columns:
        logger.info("Migrating appointment_slots schema v1 -> v2 (merging appointment_type into boolean flags)")
        _migrate_v1_to_v2(engine)
    else:
        logger.debug("appointment_slots already at v2 schema — no migration needed")


def _migrate_v1_to_v2(engine) -> None:
    """
    Rebuild appointment_slots without appointment_type column.

    For each unique (consultant_id, location_name, funding_route, slot_datetime),
    collapses multiple rows (one per appointment_type) into a single row with
    available_for_initial / available_for_follow_up boolean flags.
    """
    with engine.begin() as conn:
        # 1. Create the new table alongside the old one
        conn.execute(text("""
            CREATE TABLE appointment_slots_v2 (
                slot_id              INTEGER PRIMARY KEY AUTOINCREMENT,
                consultant_id        INTEGER NOT NULL
                                       REFERENCES consultants(consultant_id),
                consultant_name      VARCHAR(255) NOT NULL,
                profile_url          VARCHAR(512) NOT NULL,
                location_name        VARCHAR(255) NOT NULL,
                funding_route        VARCHAR(100) NOT NULL,
                slot_datetime        DATETIME     NOT NULL,
                slot_date            VARCHAR(10)  NOT NULL,
                slot_time            VARCHAR(8)   NOT NULL,
                slot_timezone        VARCHAR(50)  DEFAULT 'Europe/London',
                available_for_initial   BOOLEAN NOT NULL DEFAULT 0,
                available_for_follow_up BOOLEAN NOT NULL DEFAULT 0,
                price                VARCHAR(100),
                first_seen_at        DATETIME NOT NULL,
                last_seen_at         DATETIME NOT NULL,
                times_seen_count     INTEGER  DEFAULT 1,
                current_status       VARCHAR(20) DEFAULT 'visible',
                source_url           VARCHAR(512),
                created_at           DATETIME,
                updated_at           DATETIME,
                UNIQUE(consultant_id, location_name, funding_route, slot_datetime)
            )
        """))

        # 2. Migrate data: collapse duplicate (consultant, location, funding, datetime) rows
        #    produced by scraping initial + follow-up separately.
        #    MAX(CASE ...) aggregates the boolean flags; MIN() picks a consistent value
        #    for the scalar columns that are identical across the duplicates.
        conn.execute(text("""
            INSERT INTO appointment_slots_v2 (
                consultant_id, consultant_name, profile_url, location_name,
                funding_route, slot_datetime, slot_date, slot_time, slot_timezone,
                available_for_initial, available_for_follow_up,
                price, first_seen_at, last_seen_at, times_seen_count,
                current_status, source_url, created_at, updated_at
            )
            SELECT
                consultant_id,
                MIN(consultant_name),
                MIN(profile_url),
                location_name,
                funding_route,
                slot_datetime,
                MIN(slot_date),
                MIN(slot_time),
                MIN(slot_timezone),
                MAX(CASE WHEN appointment_type = 'initial'   THEN 1 ELSE 0 END),
                MAX(CASE WHEN appointment_type = 'follow-up' THEN 1 ELSE 0 END),
                MIN(price),
                MIN(first_seen_at),
                MAX(last_seen_at),
                MAX(times_seen_count),
                MIN(current_status),
                MIN(source_url),
                MIN(created_at),
                MAX(updated_at)
            FROM appointment_slots
            GROUP BY consultant_id, location_name, funding_route, slot_datetime
        """))

        # 3. Swap tables
        conn.execute(text("DROP TABLE appointment_slots"))
        conn.execute(text("ALTER TABLE appointment_slots_v2 RENAME TO appointment_slots"))

    logger.info("Migration v1->v2 complete")


def drop_all() -> None:
    Base.metadata.drop_all(get_engine())


if __name__ == "__main__":
    create_all()
    print("Database schema created / migrated.")
