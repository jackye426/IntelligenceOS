"""
Compute availability decay metrics for a consultant + location + funding_route combination.

T-window meaning: "slots visible when the slot_datetime was at least T days in the future."
% still visible at T-Xd: of all slots first seen with >X days to go, what fraction
were still 'visible' (not disappeared) when the slot was within X days of today?

This requires multiple scrape runs. Returns None for pct_visible until sufficient data exists.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy.orm import Session

from analysis.dataframes import load_slots_df
from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class DecayMetrics:
    consultant_id: int
    consultant_name: str
    location_name: str
    funding_route: str
    reference_dt: datetime

    # Count of currently visible slots within each T-window
    slots_within_t_windows: dict = field(default_factory=dict)  # {days: count}

    # % of first-seen slots still visible at each T-window
    # None if insufficient history (<3 scrape runs)
    pct_visible_at_t_windows: dict = field(default_factory=dict)  # {days: float|None}

    max_visible_slots_30d: int = 0
    max_visible_slots_60d: int = 0
    earliest_available_slot: datetime | None = None
    furthest_available_slot: datetime | None = None
    total_unique_slots_observed: int = 0

    def as_dict(self) -> dict:
        return {
            "consultant_id": self.consultant_id,
            "consultant_name": self.consultant_name,
            "location_name": self.location_name,
            "funding_route": self.funding_route,
            "reference_dt": self.reference_dt.isoformat(),
            "slots_within_t_windows": self.slots_within_t_windows,
            "pct_visible_at_t_windows": self.pct_visible_at_t_windows,
            "max_visible_slots_30d": self.max_visible_slots_30d,
            "max_visible_slots_60d": self.max_visible_slots_60d,
            "earliest_available_slot": self.earliest_available_slot.isoformat() if self.earliest_available_slot else None,
            "furthest_available_slot": self.furthest_available_slot.isoformat() if self.furthest_available_slot else None,
            "total_unique_slots_observed": self.total_unique_slots_observed,
        }


def compute_decay_metrics(
    session: Session,
    consultant_id: int,
    location_name: str,
    funding_route: str,
    reference_dt: datetime | None = None,
) -> DecayMetrics:
    if reference_dt is None:
        reference_dt = datetime.now(timezone.utc)

    df = load_slots_df(
        session,
        consultant_id=consultant_id,
        location_name=location_name,
        funding_route=funding_route,
    )

    consultant_name = df["consultant_name"].iloc[0] if not df.empty else "Unknown"

    metrics = DecayMetrics(
        consultant_id=consultant_id,
        consultant_name=consultant_name,
        location_name=location_name,
        funding_route=funding_route,
        reference_dt=reference_dt,
    )

    if df.empty:
        logger.warning("No slots found for %s / %s", location_name, funding_route)
        return metrics

    metrics.total_unique_slots_observed = len(df)

    # Currently visible slots
    visible = df[df["current_status"] == "visible"].copy()

    # Earliest / furthest visible
    if not visible.empty:
        future_visible = visible[visible["slot_datetime"] > reference_dt]
        if not future_visible.empty:
            metrics.earliest_available_slot = future_visible["slot_datetime"].min().to_pydatetime()
            metrics.furthest_available_slot = future_visible["slot_datetime"].max().to_pydatetime()

    # Count visible within each T-window
    for days in settings.t_windows:
        cutoff = reference_dt + timedelta(days=days)
        count = len(visible[
            (visible["slot_datetime"] > reference_dt) &
            (visible["slot_datetime"] <= cutoff)
        ])
        metrics.slots_within_t_windows[days] = count

    # Max observed visible slots in 30d / 60d windows
    # Approximated from current snapshot: max across all historical first_seen_at buckets
    metrics.max_visible_slots_30d = _max_observed_in_window(df, reference_dt, 30)
    metrics.max_visible_slots_60d = _max_observed_in_window(df, reference_dt, 60)

    # % still visible at T-windows (requires history — at least 3 scrapes)
    num_scrapes = df["first_seen_at"].nunique()
    if num_scrapes < 3:
        for days in settings.t_windows:
            metrics.pct_visible_at_t_windows[days] = None
    else:
        for days in settings.t_windows:
            pct = _compute_pct_visible_at_t(df, reference_dt, days)
            metrics.pct_visible_at_t_windows[days] = pct

    return metrics


def _max_observed_in_window(df: pd.DataFrame, reference_dt: datetime, window_days: int) -> int:
    """
    Estimate the maximum number of slots ever simultaneously visible within the next N days.
    Uses first_seen_at as a proxy for the observation point.
    """
    if df.empty:
        return 0

    cutoff = reference_dt + timedelta(days=window_days)
    window_df = df[df["slot_datetime"] <= cutoff].copy()
    if window_df.empty:
        return 0

    # Group by first_seen_at (each scrape) and count visible slots per scrape
    # current_status=visible means still visible; include disappeared too (they were visible at first_seen)
    scrape_counts = (
        window_df
        .groupby(window_df["first_seen_at"].dt.floor("min"))
        .size()
    )
    return int(scrape_counts.max()) if not scrape_counts.empty else 0


def _compute_pct_visible_at_t(df: pd.DataFrame, reference_dt: datetime, days: int) -> float | None:
    """
    Of all slots that were first seen when slot_datetime was more than `days` days away,
    what fraction are still visible (not disappeared)?

    A disappeared slot means it was present at first_seen but vanished before expiry.
    """
    if df.empty:
        return None

    days_td = timedelta(days=days)

    # Slots first seen when they were more than T days away
    eligible = df[
        (df["slot_datetime"] - df["first_seen_at"]) > days_td
    ].copy()

    if len(eligible) == 0:
        return None

    still_visible = eligible[eligible["current_status"].isin(["visible", "expired_visible"])]
    return round(len(still_visible) / len(eligible) * 100, 1)


def compute_all_metrics(session: Session, consultant_id: int) -> list[DecayMetrics]:
    """Compute metrics for all (location, funding_route) combinations for a consultant."""
    from sqlalchemy import select
    from db.models import AppointmentSlot

    rows = session.execute(
        select(AppointmentSlot.location_name, AppointmentSlot.funding_route)
        .where(AppointmentSlot.consultant_id == consultant_id)
        .distinct()
    ).all()

    results = []
    for loc, fund in rows:
        metrics = compute_decay_metrics(session, consultant_id, loc, fund)
        results.append(metrics)
    return results
