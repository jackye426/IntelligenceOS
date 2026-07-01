"""
Theoretical capacity benchmark for HCA consultant online slot supply.

Three-layer analysis:
  1. Clinic-day footprint  — which days/locations the consultant works
  2. Slot supply per clinic day — observed physical slot count per active day
  3. Theoretical capacity benchmark — observed vs hypothetical 5-day full-time schedule

Terminology rules:
  - "visible HCA public online capacity" = currently visible online slot count
  - "private outpatient footprint" = the consultant's observed clinic-day pattern
  - "share of theoretical full-time outpatient capacity" = visible / (5d x slots_per_day)
  - Do NOT call this a "utilisation rate" — that requires slot disappearance history
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy.orm import Session

from analysis.dataframes import load_slots_df

logger = logging.getLogger(__name__)

_DEFAULT_THEORETICAL_DAYS = 5
_DEFAULT_THEORETICAL_SLOTS_PER_DAY = 19


@dataclass
class CapacityBenchmark:
    consultant_id: int
    consultant_name: str
    reference_dt: datetime
    analysis_window_days: int

    # Layer 1: clinic-day footprint
    clinic_dates: list[str] = field(default_factory=list)       # YYYY-MM-DD, sorted
    days_of_week_active: list[str] = field(default_factory=list)
    locations_by_date: dict[str, str] = field(default_factory=dict)
    avg_clinic_days_per_week: float = 0.0

    # Layer 2: slot supply per clinic day
    slots_per_clinic_day: dict[str, int] = field(default_factory=dict)  # date -> count
    median_slots_per_clinic_day: float = 0.0
    modal_slots_per_clinic_day: int = 0
    max_slots_per_clinic_day: int = 0
    slots_per_week: dict[str, int] = field(default_factory=dict)        # "YYYY-WNN" -> count

    # Layer 3: theoretical capacity benchmark
    observed_slots_per_week: float = 0.0
    theoretical_days_per_week: int = _DEFAULT_THEORETICAL_DAYS
    theoretical_slots_per_day: int = _DEFAULT_THEORETICAL_SLOTS_PER_DAY
    theoretical_slots_per_week: int = 0
    visible_hca_capacity_share_pct: float = 0.0


def compute_capacity_benchmark(
    session: Session,
    consultant_id: int,
    analysis_window_days: int = 60,
    theoretical_days_per_week: int = _DEFAULT_THEORETICAL_DAYS,
    theoretical_slots_per_day: int | None = None,
    reference_dt: datetime | None = None,
) -> CapacityBenchmark:
    """
    Compute the three-layer capacity benchmark for a consultant.

    Uses follow-up-eligible slots as the physical slot superset (follow-up is always
    >= initial slots; see CLAUDE.md data model section). Deduplicates across funding
    routes so each physical slot time is counted once.
    """
    if reference_dt is None:
        reference_dt = datetime.now(timezone.utc)

    df = load_slots_df(session, consultant_id=consultant_id)

    consultant_name = df["consultant_name"].iloc[0] if not df.empty else "Unknown"

    benchmark = CapacityBenchmark(
        consultant_id=consultant_id,
        consultant_name=consultant_name,
        reference_dt=reference_dt,
        analysis_window_days=analysis_window_days,
        theoretical_days_per_week=theoretical_days_per_week,
    )

    if df.empty:
        logger.warning("No slots found for consultant_id=%d", consultant_id)
        return benchmark

    # Filter to visible future slots within the analysis window
    cutoff = reference_dt + timedelta(days=analysis_window_days)
    visible = df[
        (df["current_status"] == "visible")
        & (df["slot_datetime"] > reference_dt)
        & (df["slot_datetime"] <= cutoff)
        & (df["available_for_follow_up"] == True)
    ].copy()

    if visible.empty:
        logger.warning("No visible future slots for consultant_id=%d in next %d days", consultant_id, analysis_window_days)
        return benchmark

    # Deduplicate physical slot times across funding routes — count each datetime once
    unique_slots = visible.drop_duplicates(subset=["location_name", "slot_datetime"])

    # --- Layer 1: clinic-day footprint ---
    by_date = (
        unique_slots
        .groupby("slot_date")
        .agg(
            slot_count=("slot_datetime", "nunique"),
            location=("location_name", "first"),
        )
        .reset_index()
    )
    by_date["day_of_week"] = pd.to_datetime(by_date["slot_date"]).dt.day_name()
    by_date = by_date.sort_values("slot_date")

    benchmark.clinic_dates = by_date["slot_date"].tolist()
    benchmark.days_of_week_active = sorted(by_date["day_of_week"].unique().tolist())
    benchmark.locations_by_date = dict(zip(by_date["slot_date"], by_date["location"]))

    weeks_in_window = analysis_window_days / 7
    benchmark.avg_clinic_days_per_week = round(len(benchmark.clinic_dates) / weeks_in_window, 2)

    # --- Layer 2: slot supply per clinic day ---
    benchmark.slots_per_clinic_day = dict(zip(by_date["slot_date"], by_date["slot_count"].astype(int)))

    counts = by_date["slot_count"].astype(int)
    benchmark.median_slots_per_clinic_day = float(counts.median())
    mode_vals = counts.mode()
    benchmark.modal_slots_per_clinic_day = int(mode_vals.iloc[0]) if not mode_vals.empty else 0
    benchmark.max_slots_per_clinic_day = int(counts.max())

    # Per-ISO-week slot count
    unique_slots["iso_year"] = unique_slots["slot_datetime"].dt.isocalendar().year
    unique_slots["iso_week"] = unique_slots["slot_datetime"].dt.isocalendar().week
    weekly = unique_slots.groupby(["iso_year", "iso_week"]).size().reset_index(name="slot_count")
    benchmark.slots_per_week = {
        f"{row.iso_year}-W{int(row.iso_week):02d}": int(row.slot_count)
        for row in weekly.itertuples()
    }

    # --- Layer 3: theoretical capacity benchmark ---
    benchmark.observed_slots_per_week = round(len(unique_slots) / weeks_in_window, 1)

    if theoretical_slots_per_day is None:
        # Use the max observed slots on any single clinic date as the per-session capacity.
        # Max is more reliable than modal because near-term dates often have few remaining
        # visible slots (already booked), which drags the modal down artificially.
        theoretical_slots_per_day = int(counts.max()) if len(counts) > 0 else _DEFAULT_THEORETICAL_SLOTS_PER_DAY
    benchmark.theoretical_slots_per_day = theoretical_slots_per_day
    benchmark.theoretical_slots_per_week = theoretical_days_per_week * theoretical_slots_per_day
    benchmark.visible_hca_capacity_share_pct = round(
        benchmark.observed_slots_per_week / benchmark.theoretical_slots_per_week * 100, 1
    )

    return benchmark


def print_benchmark_report(b: CapacityBenchmark) -> None:
    """Print a formatted three-layer report to stdout."""
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ref = b.reference_dt.strftime("%Y-%m-%d")
    end = (b.reference_dt + timedelta(days=b.analysis_window_days)).strftime("%Y-%m-%d")

    print(f"\n{'='*62}")
    print(f"  PRIVATE OUTPATIENT FOOTPRINT  |  {b.consultant_name}")
    print(f"{'='*62}")
    print(f"  Analysis window : {ref} to {end} ({b.analysis_window_days} days)")
    print()

    print("LAYER 1 -- CLINIC-DAY FOOTPRINT")
    print(f"  Active day(s) of week : {', '.join(b.days_of_week_active) or 'n/a'}")
    unique_locs = sorted(set(b.locations_by_date.values()))
    for loc in unique_locs:
        print(f"  Location              : {loc}")
    print(f"  Clinic days in window : {len(b.clinic_dates)}")
    print(f"  Avg clinic days/week  : {b.avg_clinic_days_per_week:.1f}  "
          f"(vs {b.theoretical_days_per_week} theoretical full-time days/week)")
    print()

    print("LAYER 2 -- VISIBLE SLOT SUPPLY PER CLINIC DAY")
    print(f"  Max slots/clinic day    : {b.max_slots_per_clinic_day}  (used as per-session capacity in Layer 3)")
    print(f"  Median slots/clinic day : {b.median_slots_per_clinic_day:.0f}")
    print(f"  Modal slots/clinic day  : {b.modal_slots_per_clinic_day}")
    print()
    print("  Date         Day   Location                               Slots")
    print("  " + "-"*60)
    for date_str in b.clinic_dates:
        loc = b.locations_by_date.get(date_str, "")
        count = b.slots_per_clinic_day.get(date_str, 0)
        dow = pd.Timestamp(date_str).day_name()[:3]
        print(f"  {date_str}  {dow}   {loc:<38s}  {count:>3d}")
    print()

    print("LAYER 3 -- THEORETICAL CAPACITY BENCHMARK")
    wk_range = ""
    if b.slots_per_week:
        lo, hi = min(b.slots_per_week.values()), max(b.slots_per_week.values())
        wk_range = f"  (range {lo}–{hi} across individual weeks)"
    print(f"  Observed visible HCA public online capacity : ~{b.observed_slots_per_week:.1f} slots/week{wk_range}")
    print(f"  Theoretical full-time outpatient schedule   : "
          f"{b.theoretical_days_per_week} days/week x {b.theoretical_slots_per_day} slots/day "
          f"= {b.theoretical_slots_per_week} slots/week")
    print(f"  Visible HCA capacity share of theoretical   : {b.visible_hca_capacity_share_pct:.1f}%")
    print()
    print("  Note: This measures publicly visible online slot supply against a hypothetical")
    print("        5-day full-time schedule. It is NOT an appointment utilisation rate.")
    print("        Utilisation rate (booked/capacity) requires slot disappearance history.")
    print(f"{'='*62}\n")


def print_combined_report(benchmarks: list[CapacityBenchmark], no_data_names: list[str]) -> None:
    """Print an overall tally across all consultants with visible slots."""
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    active = [b for b in benchmarks if b.clinic_dates]
    if not active:
        print("No consultants with visible slots.")
        return

    total_observed = sum(b.observed_slots_per_week for b in active)
    total_theoretical = sum(b.theoretical_slots_per_week for b in active)
    combined_share = round(total_observed / total_theoretical * 100, 1) if total_theoretical else 0.0

    W = 74
    print()
    print("=" * W)
    print("  COMBINED TALLY  --  ALL CONSULTANTS WITH VISIBLE SLOTS")
    print("=" * W)
    ref = active[0].reference_dt.strftime("%Y-%m-%d")
    end = (active[0].reference_dt + timedelta(days=active[0].analysis_window_days)).strftime("%Y-%m-%d")
    print(f"  Analysis window : {ref} to {end}  |  {len(active)} consultants with data")
    print()

    col = f"  {'Consultant':<36}  {'Days/wk':>7}  {'Max/day':>7}  {'Obs/wk':>7}  {'Theor/wk':>9}  {'Share':>6}"
    print(col)
    print("  " + "-" * (W - 2))

    for b in sorted(active, key=lambda x: -x.observed_slots_per_week):
        print(
            f"  {b.consultant_name:<36}  "
            f"{b.avg_clinic_days_per_week:>7.1f}  "
            f"{b.max_slots_per_clinic_day:>7d}  "
            f"{b.observed_slots_per_week:>7.1f}  "
            f"{b.theoretical_slots_per_week:>9d}  "
            f"{b.visible_hca_capacity_share_pct:>5.1f}%"
        )

    print("  " + "-" * (W - 2))
    print(
        f"  {'TOTAL':<36}  "
        f"{'':>7}  "
        f"{'':>7}  "
        f"{total_observed:>7.1f}  "
        f"{total_theoretical:>9d}  "
        f"{combined_share:>5.1f}%"
    )
    print()
    print(f"  Theoretical benchmark: 5 days/week x each consultant's max observed slots/day")
    print(f"  Share = observed visible slots/week / theoretical full-time slots/week")
    print(f"  This is NOT a utilisation rate. Utilisation requires slot disappearance history.")
    if no_data_names:
        print()
        print(f"  No visible slots ({len(no_data_names)}): {', '.join(no_data_names)}")
    print("=" * W)
    print()


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from db.engine import get_session
    from db.migrations import create_all

    create_all()
    session = get_session()

    try:
        from sqlalchemy import select
        from db.models import Consultant

        consultants = session.execute(select(Consultant).order_by(Consultant.name)).scalars().all()
        if not consultants:
            print("No consultants in database. Run run_once.py first.")
            sys.exit(1)

        benchmarks = []
        no_data_names = []
        for c in consultants:
            b = compute_capacity_benchmark(session, c.consultant_id)
            if b.clinic_dates:
                benchmarks.append(b)
                print_benchmark_report(b)
            else:
                no_data_names.append(c.name)

        print_combined_report(benchmarks, no_data_names)
    finally:
        session.close()
