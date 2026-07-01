"""Migrate HCA monitor SQLite data into Supabase appointment tables."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import config
from common.ingestion_log import finish_run, start_run
from common.supabase_client import get_client

JOB_NAME = "hca_sqlite_migration"


def _iso(dt: str | None) -> str | None:
    if not dt:
        return None
    try:
        parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    except ValueError:
        return dt


def run_hca_migration(sqlite_path: str | None = None) -> dict[str, int]:
    db_path = Path(sqlite_path or config.HCA_SQLITE_PATH)
    if not db_path.exists():
        raise FileNotFoundError(
            f"HCA SQLite database not found at {db_path}. "
            "Run the HCA monitor scraper locally first or copy hca_monitor.db into place."
        )

    run_id = start_run(JOB_NAME, {"sqlite_path": str(db_path)})
    counts = {"rows_seen": 0, "rows_inserted": 0, "rows_updated": 0}
    client = get_client()

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT slot_id, consultant_name, profile_url, location_name,
                   funding_route, slot_datetime, current_status, source_url,
                   first_seen_at, last_seen_at
            FROM appointment_slots
            """
        )
        rows = cursor.fetchall()
        counts["rows_seen"] = len(rows)

        for row in rows:
            source_slot_id = str(row["slot_id"])
            payload: dict[str, Any] = {
                "source_system": "hca_monitor",
                "source_slot_id": source_slot_id,
                "practitioner_name": row["consultant_name"],
                "location": row["location_name"],
                "specialty": row["funding_route"],
                "starts_at": _iso(row["slot_datetime"]),
                "status": row["current_status"] or "visible",
                "booking_url": row["source_url"],
                "first_seen_at": _iso(row["first_seen_at"]),
                "last_seen_at": _iso(row["last_seen_at"]),
                "metadata": {
                    "profile_url": row["profile_url"],
                    "funding_route": row["funding_route"],
                },
            }

            existing = (
                client.table("appointment_slots")
                .select("id")
                .eq("source_system", "hca_monitor")
                .eq("source_slot_id", source_slot_id)
                .limit(1)
                .execute()
            )
            if existing.data:
                client.table("appointment_slots").update(payload).eq(
                    "id", existing.data[0]["id"]
                ).execute()
                counts["rows_updated"] += 1
            else:
                client.table("appointment_slots").insert(payload).execute()
                counts["rows_inserted"] += 1

        cursor.execute(
            """
            SELECT consultant_guid, location_guid, consultant_id, location_name,
                   funding_route, discovered_at
            FROM booking_guids
            """
        )
        guid_rows = cursor.fetchall()
        for row in guid_rows:
            booking_guid = row["consultant_guid"]
            guid_payload = {
                "source_system": "hca_monitor",
                "practitioner_name": None,
                "booking_guid": booking_guid,
                "booking_url": None,
                "first_seen_at": _iso(row["discovered_at"]),
                "last_seen_at": _iso(row["discovered_at"]),
                "metadata": {
                    "location_guid": row["location_guid"],
                    "location_name": row["location_name"],
                    "funding_route": row["funding_route"],
                    "consultant_id": row["consultant_id"],
                },
            }
            client.table("booking_guids").upsert(
                guid_payload,
                on_conflict="source_system,booking_guid",
            ).execute()

        conn.close()
        finish_run(run_id, "success", counts)
        return counts
    except Exception as exc:  # noqa: BLE001
        finish_run(run_id, "failed", counts, error=str(exc))
        raise
