"""Era detection, reproducible sampling, and age-aware tiering."""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from marketing_pipeline.tiktok.models import (
    TikTokHook,
    TikTokMarketingDataset,
    TikTokMetrics,
    TikTokPost,
    TikTokTranscript,
    TikTokVideoRecord,
)
from marketing_pipeline.tiktok.stages.performance_tier import (
    INSUFFICIENT,
    compute_performance_tiers,
    compute_rolling_tiers,
)
from marketing_pipeline.tiktok.stages.sample_plan import (
    build_sample_plan,
    catalog_hash,
    detect_eras,
)


def _catalog(n_pre=200, n_break=150, n_mature=250, seed=7):
    """Synthetic three-era catalog: flat, then a jump, then a higher plateau."""
    rng = random.Random(seed)
    start = date(2021, 1, 1)
    rows = []
    for i, base in enumerate([500] * n_pre + [15_000] * n_break + [60_000] * n_mature):
        day = start + timedelta(days=i)
        rows.append(
            {
                "video_id": f"v{i:05d}",
                "post_date_utc": day.isoformat(),
                "post_datetime_utc": f"{day.isoformat()}T12:00:00+00:00",
                "view_count": int(base * rng.uniform(0.5, 2.0)),
            }
        )
    return rows


def test_detect_eras_finds_three_phases():
    eras = detect_eras(_catalog())
    assert [e["era"] for e in eras] == ["era_1", "era_2", "era_3"]
    medians = [e["median_views"] for e in eras]
    assert medians[0] < medians[1] < medians[2]
    assert all(e["posts"] >= 25 for e in eras)


def test_sample_is_reproducible_from_the_seed():
    rows = _catalog()
    a = build_sample_plan(rows, deep=200, seed=42)
    b = build_sample_plan(rows, deep=200, seed=42)
    assert a["deep_sample"] == b["deep_sample"]
    assert a["catalog_hash"] == b["catalog_hash"]


def test_a_different_seed_gives_a_different_sample():
    rows = _catalog()
    a = build_sample_plan(rows, deep=200, seed=1)
    b = build_sample_plan(rows, deep=200, seed=2)
    assert a["deep_sample"] != b["deep_sample"]
    assert len(a["deep_sample"]) == len(b["deep_sample"])


def test_catalog_hash_tracks_content():
    rows = _catalog()
    before = catalog_hash(rows)
    rows[0]["view_count"] = (rows[0]["view_count"] or 0) + 1
    assert catalog_hash(rows) != before


def test_sample_covers_every_era_not_just_recent():
    rows = _catalog()
    plan = build_sample_plan(rows, deep=200, seed=11)
    eras_hit = {plan["era_of"][vid] for vid in plan["deep_sample"]}
    assert eras_hit == {"era_1", "era_2", "era_3"}


def test_sample_respects_the_target_size():
    rows = _catalog()
    plan = build_sample_plan(rows, deep=120, seed=3)
    assert plan["deep_sample_count"] == 120
    assert len(set(plan["deep_sample"])) == plan["deep_sample_count"]


def test_full_sample_includes_every_catalog_post():
    rows = _catalog(n_pre=25, n_break=25, n_mature=25)
    plan = build_sample_plan(rows, deep=len(rows), seed=3)
    assert plan["deep_sample_count"] == len(rows)


def test_sample_spans_tiers_within_eras():
    plan = build_sample_plan(_catalog(), deep=200, seed=5)
    tiers = {plan["tier_of"][vid] for vid in plan["deep_sample"]}
    assert {"outperform", "underperform"} <= tiers


# --------------------------------------------------------------------------
# Tiering
# --------------------------------------------------------------------------


def _video(vid: str, views: int | None, saves: int | None, posted: str) -> TikTokVideoRecord:
    return TikTokVideoRecord(
        post=TikTokPost(
            video_id=vid,
            url=f"https://www.tiktok.com/@peer/video/{vid}",
            posted_at=posted,
            metrics=TikTokMetrics(views=views, saves=saves),
        ),
        transcript=TikTokTranscript(video_id=vid, full_text="text"),
        hook=TikTokHook(video_id=vid, onscreen_hook="hook"),
    )


def _dataset(records):
    return TikTokMarketingDataset(videos={r.post.video_id: r for r in records})


def test_rolling_tiers_do_not_reward_age():
    """An old post with high absolute views is typical among its own neighbours.

    A global median would rank the whole early era as underperforming and the
    whole late era as outperforming, which is an artefact of publish date.
    """
    records = []
    start = date(2022, 1, 1)
    for i in range(120):
        views = 1_000 if i < 60 else 50_000
        day = (start + timedelta(days=i)).isoformat()
        records.append(_video(f"v{i:03d}", views, 10, f"{day}T00:00:00+00:00"))
    ds = _dataset(records)

    rolling = compute_rolling_tiers(ds)
    early = [rolling[f"v{i:03d}"]["views"] for i in range(5, 45)]
    late = [rolling[f"v{i:03d}"]["views"] for i in range(75, 115)]
    assert set(early) == {"typical"}
    assert set(late) == {"typical"}

    glob = compute_performance_tiers(ds)
    assert glob["v010"]["views"] == "underperform"
    assert glob["v100"]["views"] == "outperform"


def test_rolling_tiers_still_flag_a_local_breakout():
    records = []
    start = date(2022, 1, 1)
    for i in range(80):
        views = 100_000 if i == 40 else 1_000
        day = (start + timedelta(days=i)).isoformat()
        records.append(_video(f"v{i:03d}", views, 5, f"{day}T00:00:00+00:00"))
    rolling = compute_rolling_tiers(_dataset(records))
    assert rolling["v040"]["views"] == "outperform"
    assert rolling["v040"]["views_ratio"] > 10


def test_small_catalog_reports_insufficient_window():
    records = [
        _video(f"v{i}", 1000, 5, f"2022-01-0{i + 1}T00:00:00+00:00") for i in range(5)
    ]
    rolling = compute_rolling_tiers(_dataset(records))
    assert all(v["views"] == INSUFFICIENT for v in rolling.values())
    assert all(v["views_ratio"] is None for v in rolling.values())


def test_window_metadata_is_reported():
    records = [
        _video(f"v{i:03d}", 1000, 5, f"2022-01-01T00:00:{i:02d}+00:00") for i in range(60)
    ]
    rolling = compute_rolling_tiers(_dataset(records))
    entry = rolling["v030"]
    assert entry["window_n"] == 40
    assert entry["window_from"] is not None
    assert entry["basis"] == "rolling"


def test_missing_saves_are_excluded_not_zeroed():
    """A peer catalog often has no saves. That must not collapse the median."""
    records = [_video(f"v{i:03d}", 1000, None, f"2022-01-01T00:00:{i:02d}+00:00") for i in range(60)]
    records.append(_video("has_saves", 1000, 50, "2022-01-01T00:01:00+00:00"))
    tiers = compute_performance_tiers(_dataset(records))
    # One real measurement present, so the median equals it and that post is typical.
    assert tiers["has_saves"]["saves_per_1k"] == "typical"
    assert tiers["has_saves"]["cohort_median_saves_per_1k"] == pytest.approx(50.0)
    # Posts with no saves data are not labelled underperform on invented zeros.
    assert tiers["v000"]["saves_per_1k"] == "typical"


def test_all_metrics_missing_yields_no_median():
    records = [_video(f"v{i}", None, None, f"2022-01-0{i + 1}T00:00:00+00:00") for i in range(4)]
    tiers = compute_performance_tiers(_dataset(records))
    assert tiers["v0"]["cohort_median_views"] is None
    assert tiers["v0"]["views"] == "typical"
