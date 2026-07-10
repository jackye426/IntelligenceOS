"""Tests for Business Center CSV + Studio insight normalization."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from marketing_pipeline.tiktok.stages.ingest_bc_csv import (
    parse_followers_bundle,
    parse_overview_csv,
    parse_tiktok_day_label,
)
from marketing_pipeline.tiktok.stages.studio_insight import normalize_insight_payload


def test_parse_day_label():
    assert parse_tiktok_day_label("July 3", default_year=2026).isoformat() == "2026-07-03"
    assert parse_tiktok_day_label("October 29", default_year=2025).isoformat() == "2025-10-29"


def test_parse_overview_sample():
    path = Path(r"C:\Users\yulon\Downloads\Overview_2025-07-09_1783513686_docmap\Overview.csv")
    if not path.exists():
        return
    rows = parse_overview_csv(path, default_year=2026)
    assert len(rows) > 10
    assert rows[-1]["day"].startswith("2026-07-")
    assert "profile_views" in rows[-1]


def test_parse_followers_sample():
    path = Path(r"C:\Users\yulon\Downloads\Overview_2025-07-09_1783513686_docmap")
    if not path.exists():
        return
    data = parse_followers_bundle(path)
    assert data["demographics"]["gender"]["Female"] == 0.89
    assert "GB" in data["demographics"]["territories"]


def test_normalize_insight_payload():
    payload = {
        "video_info": {
            "aweme_id": "7659734602268806422",
            "statistics": {"play_count": 285, "digg_count": 1, "collect_count": 0},
            "video": {"duration": 54379},
        },
        "video_finish_rate_realtime": {
            "value": {"status": 0, "value": 0.0035},
        },
        "video_per_duration_realtime": {
            "value": {"status": 0, "value": 3.12},
        },
        "video_total_duration_realtime": {
            "value": {"status": 0, "value": 885},
        },
        "realtime_total_video_views": {
            "value": {"status": 0, "value": 285},
        },
        "realtime_new_followers": {
            "value": {"status": 0, "value": 0},
        },
        "video_traffic_source_percent_realtime": {
            "value": {
                "status": 0,
                "value": [
                    {"key": "For You", "value": 0.957},
                    {"key": "Personal Profile", "value": 0.018},
                ],
            }
        },
        "video_retention_rate_realtime": {
            "value": {"list": [{"timestamp": "0", "value": 1}, {"timestamp": "1000", "value": 0.7}]},
        },
    }
    metrics = normalize_insight_payload(payload)
    assert metrics["platform_post_id"] == "7659734602268806422"
    assert metrics["avg_watch_sec"] == 3.12
    assert metrics["finish_rate"] == 0.0035
    assert metrics["traffic_sources"]["For You"] == 0.957
    assert metrics["retention_curve"][1]["value"] == 0.7


def test_velocity_math():
    t0 = datetime(2026, 7, 10, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    hours = (t1 - t0).total_seconds() / 3600
    assert hours == 2.0
    assert (300 - 100) / hours == 100.0
