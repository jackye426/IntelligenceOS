"""Supabase client + appointment_slots lifecycle upsert for Spire."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from spire_monitor.config import SOURCE_SYSTEM, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL

logger = logging.getLogger(__name__)

_T48H = timedelta(hours=48)
_client = None


def get_client():
    global _client
    if _client is not None:
        return _client
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_SERVICE_KEY) must be set"
        )
    from supabase import create_client

    _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return _client


def source_slot_id(consultant_id: str, location_id: str, starts_at: datetime) -> str:
    # Naive local wall time from Spire SAPDateTime — store as-is with Z-less ISO for key stability
    return f"{consultant_id}:{location_id}:{starts_at.strftime('%Y-%m-%dT%H:%M:%S')}"


def _to_timestamptz(dt: datetime) -> str:
    """Treat Spire naive datetimes as Europe/London wall time → UTC ISO."""
    if dt.tzinfo is None:
        try:
            from zoneinfo import ZoneInfo

            dt = dt.replace(tzinfo=ZoneInfo("Europe/London"))
        except Exception:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def start_ingestion_run(metadata: dict[str, Any] | None = None) -> str | None:
    try:
        client = get_client()
        result = (
            client.table("data_ingestion_runs")
            .insert(
                {
                    "job_name": "spire_appointment_scrape",
                    "status": "started",
                    "metadata": metadata or {},
                }
            )
            .execute()
        )
        return result.data[0]["id"]
    except Exception as e:
        logger.warning("Could not start data_ingestion_runs row: %s", e)
        return None


def finish_ingestion_run(
    run_id: str | None,
    status: str,
    counts: dict[str, int],
    error: str | None = None,
) -> None:
    if not run_id:
        return
    try:
        client = get_client()
        client.table("data_ingestion_runs").update(
            {
                "status": status,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "rows_seen": counts.get("rows_seen", 0),
                "rows_inserted": counts.get("rows_inserted", 0),
                "rows_updated": counts.get("rows_updated", 0),
                "error": error,
            }
        ).eq("id", run_id).execute()
    except Exception as e:
        logger.warning("Could not finish data_ingestion_runs row: %s", e)


def upsert_consultant_slots(
    *,
    consultant_id: str,
    consultant_name: str,
    profile_url: str,
    slots: list[dict],
    collection_ts: datetime | None = None,
) -> dict[str, int]:
    """
    Upsert visible slots for one consultant; mark missing future slots disappeared/expired.

    Schema statuses: visible | booked | expired | disappeared | unknown
    """
    if collection_ts is None:
        collection_ts = datetime.now(timezone.utc)
    elif collection_ts.tzinfo is None:
        collection_ts = collection_ts.replace(tzinfo=timezone.utc)

    client = get_client()
    counts = {"rows_seen": len(slots), "rows_inserted": 0, "rows_updated": 0, "disappeared": 0, "expired": 0}

    incoming_ids: set[str] = set()
    now_iso = collection_ts.isoformat()

    for s in slots:
        starts: datetime = s["starts_at"]
        sid = source_slot_id(consultant_id, s["location_id"], starts)
        incoming_ids.add(sid)
        payload: dict[str, Any] = {
            "source_system": SOURCE_SYSTEM,
            "source_slot_id": sid,
            "practitioner_name": consultant_name,
            "practitioner_id": consultant_id,
            "location": s["location_name"],
            "specialty": None,
            "starts_at": _to_timestamptz(starts),
            "ends_at": None,
            "status": "visible",
            "booking_url": profile_url,
            "last_seen_at": now_iso,
            "metadata": {
                "location_id": s["location_id"],
                "amount": s.get("amount"),
                "duration": s.get("duration"),
                "currency": s.get("currency"),
                "organisation_unit": s.get("organisation_unit"),
                "profile_url": profile_url,
                "funding_route": "self-pay",
            },
        }
        if s.get("duration"):
            try:
                mins = int(s["duration"])
                ends = starts + timedelta(minutes=mins)
                payload["ends_at"] = _to_timestamptz(ends)
            except (TypeError, ValueError):
                pass

        existing = (
            client.table("appointment_slots")
            .select("id, first_seen_at")
            .eq("source_system", SOURCE_SYSTEM)
            .eq("source_slot_id", sid)
            .limit(1)
            .execute()
        )
        if existing.data:
            client.table("appointment_slots").update(payload).eq(
                "id", existing.data[0]["id"]
            ).execute()
            counts["rows_updated"] += 1
        else:
            payload["first_seen_at"] = now_iso
            client.table("appointment_slots").insert(payload).execute()
            counts["rows_inserted"] += 1

    # Mark previously-visible slots for this practitioner absent from this scrape
    existing_visible = (
        client.table("appointment_slots")
        .select("id, source_slot_id, starts_at, status")
        .eq("source_system", SOURCE_SYSTEM)
        .eq("practitioner_id", consultant_id)
        .eq("status", "visible")
        .execute()
    )

    t48h = collection_ts + _T48H
    for row in existing_visible.data or []:
        sid = row.get("source_slot_id")
        if not sid or sid in incoming_ids:
            continue
        starts_raw = row.get("starts_at")
        try:
            starts_at = datetime.fromisoformat(str(starts_raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=timezone.utc)

        new_status = "expired" if starts_at <= t48h else "disappeared"
        client.table("appointment_slots").update(
            {"status": new_status, "updated_at": now_iso}
        ).eq("id", row["id"]).execute()
        counts[new_status] = counts.get(new_status, 0) + 1

    logger.info(
        "Upsert %s: +%d / ~%d / -%d disappeared / ~%d expired (seen %d)",
        consultant_name,
        counts["rows_inserted"],
        counts["rows_updated"],
        counts.get("disappeared", 0),
        counts.get("expired", 0),
        counts["rows_seen"],
    )
    return counts
