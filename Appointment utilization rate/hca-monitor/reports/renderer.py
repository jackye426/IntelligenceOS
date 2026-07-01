"""
Build HTML reports from the analysis layer using Jinja2 templates.
Outputs to ./output/ directory.
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from jinja2 import Environment, FileSystemLoader

from analysis.capacity_benchmark import CapacityBenchmark, compute_capacity_benchmark
from analysis.hours_comparison import compare_hours
from analysis.metrics import compute_all_metrics
from config.settings import settings
from db.engine import get_session
from db.models import Consultant
from sqlalchemy import select

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_OUTPUT_DIR = Path("output")
_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_TZ_LONDON = ZoneInfo("Europe/London")


def _share_color(pct: float) -> str:
    """Return a CSS hex colour on a grey→blue gradient based on share percentage."""
    if pct >= 40:
        return "#0d6efd"
    if pct >= 25:
        return "#0dcaf0"
    if pct >= 15:
        return "#6ea8fe"
    if pct >= 8:
        return "#adb5bd"
    return "#ced4da"


def _jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=True,
    )
    env.globals["share_color"] = _share_color
    return env


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")


# ── Capacity benchmark report ────────────────────────────────────────────────

def _benchmark_template_data(b: CapacityBenchmark) -> dict:
    """Convert a CapacityBenchmark into a flat dict ready for the Jinja template."""
    max_day = b.max_slots_per_clinic_day or 1
    clinic_date_rows = [
        {
            "date": date_str,
            "dow": pd.Timestamp(date_str).day_name(),
            "location": b.locations_by_date.get(date_str, ""),
            "count": b.slots_per_clinic_day.get(date_str, 0),
            "fill_pct": b.slots_per_clinic_day.get(date_str, 0) / max_day * 100,
        }
        for date_str in b.clinic_dates
    ]
    wk_vals = list(b.slots_per_week.values())
    weekly_range = f"{min(wk_vals)}–{max(wk_vals)}" if wk_vals else "n/a"

    return {
        "consultant_name": b.consultant_name,
        "slug": _slug(b.consultant_name),
        "avg_clinic_days_per_week": b.avg_clinic_days_per_week,
        "days_of_week_active": b.days_of_week_active,
        "unique_locations": sorted(set(b.locations_by_date.values())),
        "clinic_dates": b.clinic_dates,
        "clinic_date_rows": clinic_date_rows,
        "max_slots_per_clinic_day": b.max_slots_per_clinic_day,
        "median_slots_per_clinic_day": b.median_slots_per_clinic_day,
        "slots_per_week": b.slots_per_week,
        "weekly_range": weekly_range,
        "observed_slots_per_week": b.observed_slots_per_week,
        "theoretical_slots_per_week": b.theoretical_slots_per_week,
        "visible_hca_capacity_share_pct": b.visible_hca_capacity_share_pct,
    }


def render_capacity_benchmark_report(session=None) -> str:
    """
    Generate the combined capacity benchmark HTML report for all consultants.
    Returns the output file path.
    """
    _OUTPUT_DIR.mkdir(exist_ok=True)
    close_session = session is None
    if session is None:
        session = get_session()

    try:
        consultants = session.execute(select(Consultant).order_by(Consultant.name)).scalars().all()
        reference_dt = datetime.now(timezone.utc)
        generated_at = datetime.now(_TZ_LONDON).strftime("%Y-%m-%d %H:%M:%S %Z")

        benchmarks_data = []
        no_data_names = []

        for c in consultants:
            b = compute_capacity_benchmark(session, c.consultant_id, reference_dt=reference_dt)
            if b.clinic_dates:
                benchmarks_data.append(_benchmark_template_data(b))
            else:
                no_data_names.append(c.name)

        total_observed = sum(d["observed_slots_per_week"] for d in benchmarks_data)
        total_theoretical = sum(d["theoretical_slots_per_week"] for d in benchmarks_data)
        combined_share = round(total_observed / total_theoretical * 100, 1) if total_theoretical else 0.0

        window_end = reference_dt + timedelta(days=60)
        env = _jinja_env()
        html = env.get_template("capacity_benchmark.html").render(
            generated_at=generated_at,
            window_start=reference_dt.strftime("%Y-%m-%d"),
            window_end=window_end.strftime("%Y-%m-%d"),
            window_days=60,
            benchmarks=sorted(benchmarks_data, key=lambda d: -d["observed_slots_per_week"]),
            active_count=len(benchmarks_data),
            no_data_names=no_data_names,
            total_observed_per_week=total_observed,
            total_theoretical_per_week=total_theoretical,
            combined_share_pct=combined_share,
        )

        date_slug = reference_dt.strftime("%Y%m%d")
        out_path = _OUTPUT_DIR / f"capacity_benchmark_{date_slug}.html"
        out_path.write_text(html, encoding="utf-8")
        logger.info("Written: %s", out_path)
        return str(out_path)
    finally:
        if close_session:
            session.close()


# ── Availability decay + hours comparison reports ───────────────────────────

def render_all_reports() -> list[str]:
    """Generate all reports for all consultants. Returns list of output file paths."""
    _OUTPUT_DIR.mkdir(exist_ok=True)
    session = get_session()
    env = _jinja_env()
    generated = []

    try:
        consultants = session.execute(select(Consultant)).scalars().all()
        for c in consultants:
            paths = _render_consultant_reports(session, env, c)
            generated.extend(paths)

        benchmark_path = render_capacity_benchmark_report(session=session)
        generated.append(benchmark_path)
    finally:
        session.close()

    return generated


def _render_consultant_reports(session, env: Environment, consultant: Consultant) -> list[str]:
    generated_at = datetime.now(_TZ_LONDON).strftime("%Y-%m-%d %H:%M:%S %Z")
    reference_dt = datetime.now(timezone.utc)

    paths = []

    # Availability decay report
    metrics_list = compute_all_metrics(session, consultant.consultant_id)
    decay_html = env.get_template("availability_decay.html").render(
        consultant_name=consultant.name,
        generated_at=generated_at,
        reference_date=reference_dt.astimezone(_TZ_LONDON).strftime("%Y-%m-%d"),
        metrics_list=[m.as_dict() for m in metrics_list],
        t_windows=settings.t_windows,
    )
    decay_path = _OUTPUT_DIR / f"{_slug(consultant.name)}_availability_decay.html"
    decay_path.write_text(decay_html, encoding="utf-8")
    logger.info("Written: %s", decay_path)
    paths.append(str(decay_path))

    # Published hours comparison report
    comparisons = compare_hours(session, consultant.consultant_id)
    hours_html = env.get_template("hours_comparison.html").render(
        consultant_name=consultant.name,
        generated_at=generated_at,
        comparisons=[c.as_dict() for c in comparisons],
        day_names=_DAY_NAMES,
    )
    hours_path = _OUTPUT_DIR / f"{_slug(consultant.name)}_hours_comparison.html"
    hours_path.write_text(hours_html, encoding="utf-8")
    logger.info("Written: %s", hours_path)
    paths.append(str(hours_path))

    return paths


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    from db.migrations import create_all
    create_all()
    path = render_capacity_benchmark_report()
    print(f"Report written to: {path}")
