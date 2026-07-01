"""
Compare published consultant hours (from profile) against observed online appointment slots.

Output: per-location comparison showing published days/hours vs actual slot distribution.
"""

import json
import logging
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy.orm import Session

from analysis.dataframes import load_slots_df
from db.models import ConsultantLocation

_TZ_LONDON = ZoneInfo("Europe/London")
_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

logger = logging.getLogger(__name__)


@dataclass
class LocationHoursComparison:
    location_name: str
    published_days: list[str]
    published_hours: str | None
    days_with_observed_slots: list[str]
    days_published_not_observed: list[str]
    days_observed_not_published: list[str]
    earliest_observed_time: str | None        # HH:MM
    latest_observed_time: str | None          # HH:MM
    slot_count_by_day: dict = field(default_factory=dict)  # {"Monday": 5, ...}
    total_slots_observed: int = 0
    interpretation: str = ""

    def as_dict(self) -> dict:
        return {
            "location_name": self.location_name,
            "published_days": self.published_days,
            "published_hours": self.published_hours,
            "days_with_observed_slots": self.days_with_observed_slots,
            "days_published_not_observed": self.days_published_not_observed,
            "days_observed_not_published": self.days_observed_not_published,
            "earliest_observed_time": self.earliest_observed_time,
            "latest_observed_time": self.latest_observed_time,
            "slot_count_by_day": self.slot_count_by_day,
            "total_slots_observed": self.total_slots_observed,
            "interpretation": self.interpretation,
        }


def compare_hours(session: Session, consultant_id: int) -> list[LocationHoursComparison]:
    from sqlalchemy import select

    locations = session.execute(
        select(ConsultantLocation).where(ConsultantLocation.consultant_id == consultant_id)
    ).scalars().all()

    results = []
    for loc in locations:
        published_days = json.loads(loc.published_days) if loc.published_days else []
        df = load_slots_df(session, consultant_id=consultant_id, location_name=loc.location_name)

        if df.empty:
            comp = LocationHoursComparison(
                location_name=loc.location_name,
                published_days=published_days,
                published_hours=loc.published_hours,
                days_with_observed_slots=[],
                days_published_not_observed=published_days,
                days_observed_not_published=[],
                interpretation="No online slots observed at this location.",
            )
            results.append(comp)
            continue

        # Day-of-week analysis using London timezone
        df["day_of_week"] = df["slot_datetime"].dt.tz_convert("Europe/London").dt.day_name()
        slot_count_by_day = df.groupby("day_of_week").size().to_dict()
        # Fill zeros for days not observed
        full_count = {day: slot_count_by_day.get(day, 0) for day in _DAY_NAMES}

        days_with_slots = [d for d, c in full_count.items() if c > 0]
        days_pub_not_obs = [d for d in published_days if d not in days_with_slots]
        days_obs_not_pub = [d for d in days_with_slots if d and d not in published_days]

        # Time range
        slot_times = df["slot_time"].dropna().sort_values()
        earliest_time = slot_times.iloc[0] if not slot_times.empty else None
        latest_time = slot_times.iloc[-1] if not slot_times.empty else None

        interpretation = _build_interpretation(
            loc.location_name,
            published_days,
            loc.published_hours,
            days_with_slots,
            days_pub_not_obs,
            days_obs_not_pub,
            len(df),
        )

        comp = LocationHoursComparison(
            location_name=loc.location_name,
            published_days=published_days,
            published_hours=loc.published_hours,
            days_with_observed_slots=days_with_slots,
            days_published_not_observed=days_pub_not_obs,
            days_observed_not_published=days_obs_not_pub,
            earliest_observed_time=earliest_time,
            latest_observed_time=latest_time,
            slot_count_by_day=full_count,
            total_slots_observed=len(df),
            interpretation=interpretation,
        )
        results.append(comp)

    return results


def _build_interpretation(
    location: str,
    published_days: list[str],
    published_hours: str | None,
    observed_days: list[str],
    pub_not_obs: list[str],
    obs_not_pub: list[str],
    total_slots: int,
) -> str:
    parts = [f"Location: {location}"]
    if published_days:
        parts.append(f"Published profile days: {', '.join(published_days)}")
    if published_hours:
        parts.append(f"Published profile hours: {published_hours}")
    parts.append(f"Observed online slots on: {', '.join(observed_days) if observed_days else 'none'}")
    parts.append(f"Total slots observed: {total_slots}")
    if pub_not_obs:
        parts.append(
            f"Days in published schedule with no online slots: {', '.join(pub_not_obs)}"
        )
    if obs_not_pub:
        parts.append(
            f"Days with online slots not in published schedule: {', '.join(obs_not_pub)}"
        )
    if not observed_days:
        parts.append(
            "Interpretation: published hours are listed but no public online booking slots have been observed."
        )
    elif pub_not_obs:
        parts.append(
            "Interpretation: published hours are broader than public online slot inventory."
        )
    else:
        parts.append(
            "Interpretation: observed online slots align with or exceed published consulting days."
        )
    return "\n".join(parts)
