"""Availability decay metrics for Spire slots in Supabase."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from spire_monitor.config import SOURCE_SYSTEM, T_WINDOWS_DAYS
from spire_monitor.store import get_client

logger = logging.getLogger(__name__)


@dataclass
class DecayMetrics:
    practitioner_id: str
    practitioner_name: str
    location: str | None
    reference_dt: datetime
    slots_within_t_windows: dict[int, int] = field(default_factory=dict)
    pct_visible_at_t_windows: dict[int, float | None] = field(default_factory=dict)
    total_unique_slots: int = 0
    currently_visible: int = 0
    disappeared: int = 0
    expired: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "practitioner_id": self.practitioner_id,
            "practitioner_name": self.practitioner_name,
            "location": self.location,
            "reference_dt": self.reference_dt.isoformat(),
            "slots_within_t_windows": self.slots_within_t_windows,
            "pct_visible_at_t_windows": self.pct_visible_at_t_windows,
            "total_unique_slots": self.total_unique_slots,
            "currently_visible": self.currently_visible,
            "disappeared": self.disappeared,
            "expired": self.expired,
        }


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def fetch_slots(practitioner_id: str) -> list[dict]:
    client = get_client()
    result = (
        client.table("appointment_slots")
        .select(
            "practitioner_id,practitioner_name,location,starts_at,status,first_seen_at,last_seen_at"
        )
        .eq("source_system", SOURCE_SYSTEM)
        .eq("practitioner_id", practitioner_id)
        .execute()
    )
    return result.data or []


def compute_decay_metrics(
    practitioner_id: str,
    *,
    reference_dt: datetime | None = None,
) -> DecayMetrics:
    if reference_dt is None:
        reference_dt = datetime.now(timezone.utc)
    elif reference_dt.tzinfo is None:
        reference_dt = reference_dt.replace(tzinfo=timezone.utc)

    rows = fetch_slots(practitioner_id)
    name = rows[0]["practitioner_name"] if rows else practitioner_id
    locations = {r.get("location") for r in rows if r.get("location")}
    location = next(iter(locations), None) if len(locations) == 1 else None

    metrics = DecayMetrics(
        practitioner_id=practitioner_id,
        practitioner_name=name,
        location=location,
        reference_dt=reference_dt,
        total_unique_slots=len(rows),
    )

    parsed: list[dict] = []
    for r in rows:
        starts = _parse_dt(r.get("starts_at"))
        first = _parse_dt(r.get("first_seen_at"))
        if not starts:
            continue
        status = r.get("status") or "unknown"
        parsed.append({"starts_at": starts, "first_seen_at": first, "status": status})
        if status == "visible":
            metrics.currently_visible += 1
        elif status == "disappeared":
            metrics.disappeared += 1
        elif status == "expired":
            metrics.expired += 1

    visible = [p for p in parsed if p["status"] == "visible"]
    for days in T_WINDOWS_DAYS:
        cutoff = reference_dt + timedelta(days=days)
        metrics.slots_within_t_windows[days] = sum(
            1
            for p in visible
            if reference_dt < p["starts_at"] <= cutoff
        )

    # Need multiple observation times for survival %
    first_seen_times = {p["first_seen_at"] for p in parsed if p["first_seen_at"]}
    if len(first_seen_times) < 3:
        for days in T_WINDOWS_DAYS:
            metrics.pct_visible_at_t_windows[days] = None
    else:
        for days in T_WINDOWS_DAYS:
            metrics.pct_visible_at_t_windows[days] = _pct_visible_at_t(
                parsed, days
            )

    return metrics


def _pct_visible_at_t(parsed: list[dict], days: int) -> float | None:
    days_td = timedelta(days=days)
    eligible = [
        p
        for p in parsed
        if p["first_seen_at"] and (p["starts_at"] - p["first_seen_at"]) > days_td
    ]
    if not eligible:
        return None
    still = [p for p in eligible if p["status"] in {"visible", "expired"}]
    return round(len(still) / len(eligible) * 100, 1)


def compute_all_roster_metrics(practitioner_ids: list[str]) -> list[DecayMetrics]:
    return [compute_decay_metrics(pid) for pid in practitioner_ids]
