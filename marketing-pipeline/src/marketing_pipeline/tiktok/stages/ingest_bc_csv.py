"""Ingest TikTok Business Center / Studio CSV exports (Overview + Followers)."""

from __future__ import annotations

import csv
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from marketing_pipeline.shared.ingestion_log import finish_run, start_run
from marketing_pipeline.shared.supabase_client import get_client

logger = logging.getLogger(__name__)

JOB_NAME = "tiktok_bc_csv_ingest"

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def parse_tiktok_day_label(label: str, *, default_year: int | None = None) -> date | None:
    """Parse Overview/FollowerHistory labels like 'July 3' or 'October 29'."""
    text = (label or "").strip()
    if not text:
        return None
    # Already ISO
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    m = re.match(r"^([A-Za-z]+)\s+(\d{1,2})(?:,?\s*(\d{4}))?$", text)
    if not m:
        return None
    month = _MONTHS.get(m.group(1).lower())
    if not month:
        return None
    day = int(m.group(2))
    year = int(m.group(3)) if m.group(3) else (default_year or datetime.now(timezone.utc).year)
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def assign_years_to_day_labels(
    labels: list[str],
    *,
    end_year: int | None = None,
) -> list[date | None]:
    """Assign calendar years to TikTok 'Month Day' labels spanning a rolling window.

    Exports are chronological; when month goes backwards (Dec → Jan) or jumps
    down sharply, bump the year. ``end_year`` is the year of the last row
    (defaults to current UTC year).
    """
    end_year = end_year or datetime.now(timezone.utc).year
    parsed: list[tuple[int, int] | None] = []
    for label in labels:
        text = (label or "").strip()
        m = re.match(r"^([A-Za-z]+)\s+(\d{1,2})(?:,?\s*(\d{4}))?$", text)
        if not m:
            # ISO passthrough handled by caller
            try:
                d = date.fromisoformat(text[:10])
                parsed.append((d.year, d.month * 100 + d.day))
            except ValueError:
                parsed.append(None)
            continue
        month = _MONTHS.get(m.group(1).lower())
        if not month:
            parsed.append(None)
            continue
        if m.group(3):
            parsed.append((int(m.group(3)), month * 100 + int(m.group(2))))
            continue
        parsed.append((None, month * 100 + int(m.group(2))))

    # Walk backwards from the end assigning years
    years: list[int | None] = [None] * len(parsed)
    current_year = end_year
    prev_ord: int | None = None
    for i in range(len(parsed) - 1, -1, -1):
        item = parsed[i]
        if item is None:
            continue
        explicit_year, ord_ = item
        if explicit_year is not None:
            current_year = explicit_year
            years[i] = explicit_year
            prev_ord = ord_
            continue
        if prev_ord is not None and ord_ > prev_ord:
            # e.g. walking back from July into December → previous calendar year
            current_year -= 1
        years[i] = current_year
        prev_ord = ord_

    out: list[date | None] = []
    for i, label in enumerate(labels):
        if years[i] is None:
            out.append(parse_tiktok_day_label(label, default_year=end_year))
            continue
        out.append(parse_tiktok_day_label(label, default_year=years[i]))
    return out


def parse_overview_csv(
    path: Path,
    *,
    default_year: int | None = None,
) -> list[dict[str, Any]]:
    raw_rows = _read_csv(path)
    labels = [r.get("Date") or "" for r in raw_rows]
    days = assign_years_to_day_labels(labels, end_year=default_year)
    rows_out: list[dict[str, Any]] = []
    for row, day in zip(raw_rows, days):
        if not day:
            continue

        def _int(key: str) -> int | None:
            raw = (row.get(key) or "").strip()
            if raw == "" or raw.lower() == "undefined":
                return None
            try:
                return int(float(raw.replace(",", "")))
            except ValueError:
                return None

        rows_out.append(
            {
                "day": day.isoformat(),
                "video_views": _int("Video Views"),
                "profile_views": _int("Profile Views"),
                "likes": _int("Likes"),
                "comments": _int("Comments"),
                "shares": _int("Shares"),
            }
        )
    return rows_out


def parse_followers_bundle(directory: Path) -> dict[str, Any]:
    """Parse Follower*.csv files from an export folder or unzipped Followers zip."""
    demographics: dict[str, Any] = {}
    follower_count: int | None = None

    gender_path = directory / "FollowerGender.csv"
    if gender_path.exists():
        demographics["gender"] = {
            (r.get("Gender") or ""): float(r.get("Distribution") or 0)
            for r in _read_csv(gender_path)
            if r.get("Gender")
        }

    terr_path = directory / "FollowerTopTerritories.csv"
    if terr_path.exists():
        demographics["territories"] = {
            (r.get("Top territories") or ""): float(r.get("Distribution") or 0)
            for r in _read_csv(terr_path)
            if r.get("Top territories")
        }

    activity_path = directory / "FollowerActivity.csv"
    if activity_path.exists():
        demographics["activity"] = [
            {
                "date": r.get("Date"),
                "hour": int(r["Hour"]) if (r.get("Hour") or "").isdigit() else r.get("Hour"),
                "active_followers": int(r["Active followers"])
                if (r.get("Active followers") or "").replace("-", "").isdigit()
                else r.get("Active followers"),
            }
            for r in _read_csv(activity_path)
        ]

    history_path = directory / "FollowerHistory.csv"
    if history_path.exists():
        history = []
        for r in _read_csv(history_path):
            raw = (r.get("Followers") or "").strip()
            if raw.lower() in {"", "undefined"}:
                continue
            try:
                count = int(float(raw.replace(",", "")))
            except ValueError:
                continue
            day = parse_tiktok_day_label(r.get("Date") or "")
            history.append({"date": day.isoformat() if day else r.get("Date"), "followers": count})
            follower_count = count
        demographics["follower_history"] = history

    return {"follower_count": follower_count, "demographics": demographics}


def ingest_business_center_export(
    directory: Path,
    *,
    account_handle: str = "docmap",
    default_year: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Ingest Overview.csv + optional Follower*.csv from an export directory."""
    directory = Path(directory)
    run_id = start_run(
        JOB_NAME,
        {"directory": str(directory), "account_handle": account_handle, "dry_run": dry_run},
    )
    try:
        overview_path = directory / "Overview.csv"
        daily_rows = parse_overview_csv(overview_path, default_year=default_year) if overview_path.exists() else []

        audience = parse_followers_bundle(directory)
        has_audience = bool(audience.get("demographics"))

        client = get_client()
        upserted = 0
        if daily_rows and not dry_run:
            for row in daily_rows:
                payload = {
                    "account_handle": account_handle,
                    "day": row["day"],
                    "source": "business_center_csv",
                    "video_views": row["video_views"],
                    "profile_views": row["profile_views"],
                    "likes": row["likes"],
                    "comments": row["comments"],
                    "shares": row["shares"],
                    "metrics": row,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                client.table("tiktok_account_daily").upsert(
                    payload,
                    on_conflict="account_handle,day,source",
                ).execute()
                upserted += 1
        elif dry_run:
            upserted = len(daily_rows)

        audience_inserted = 0
        if has_audience and not dry_run:
            client.table("tiktok_audience_snapshots").insert(
                {
                    "account_handle": account_handle,
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "source": "business_center_csv",
                    "follower_count": audience.get("follower_count"),
                    "demographics": audience.get("demographics") or {},
                    "raw": {"files": [p.name for p in directory.glob("*.csv")]},
                }
            ).execute()
            audience_inserted = 1
        elif has_audience and dry_run:
            audience_inserted = 1

        counts = {
            "rows_seen": len(daily_rows) + (1 if has_audience else 0),
            "rows_inserted": audience_inserted,
            "rows_updated": upserted,
        }
        finish_run(run_id, "success", counts)
        return {
            **counts,
            "daily_days": len(daily_rows),
            "follower_count": audience.get("follower_count"),
            "dry_run": dry_run,
        }
    except Exception as exc:
        finish_run(run_id, "failed", {}, error=str(exc))
        raise
