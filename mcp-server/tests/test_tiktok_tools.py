"""Unit tests for TikTok MCP helpers (no live Supabase)."""

from __future__ import annotations

from tools.tiktok_shared import (
    aggregate_ab_tests,
    cohort_medians,
    engagement_total,
    rank_posts,
    saves_per_1k,
    winner_video_id,
)


def _row(vid: str, views: int, saves: int, likes: int = 0, ab_pairs: list | None = None):
    return {
        "platform_post_id": vid,
        "hook": f"hook-{vid}",
        "metrics": {
            "views": views,
            "saves": saves,
            "likes": likes,
            "comments": 0,
            "shares": 0,
            "saves_per_1k_views": round((saves / views) * 1000, 2) if views else 0,
        },
        "metadata": {
            "hook_detail": {"hook_source": "ocr", "onscreen_hook": f"hook-{vid}"},
            "ab_pairs": ab_pairs or [],
        },
    }


def test_rank_posts_by_views_vs_saves_per_1k():
    rows = [
        _row("high-views", views=100_000, saves=500),
        _row("high-saves", views=1_000, saves=200),
    ]
    by_views = rank_posts(rows, "views")
    by_saves = rank_posts(rows, "saves_per_1k")
    assert by_views[0]["platform_post_id"] == "high-views"
    assert by_saves[0]["platform_post_id"] == "high-saves"


def test_engagement_total():
    assert engagement_total({"likes": 10, "comments": 5, "shares": 2}) == 17


def test_aggregate_ab_tests_all_edges():
    rows = [
        _row(
            "a",
            1000,
            50,
            ab_pairs=[{"pair_id": "p1", "partner_video_id": "b", "learning": "test"}],
        ),
        _row(
            "b",
            2000,
            100,
            ab_pairs=[{"pair_id": "p1", "partner_video_id": "a", "learning": "test"}],
        ),
        _row(
            "c",
            500,
            10,
            ab_pairs=[{"pair_id": "p1", "partner_video_id": "a", "learning": "test"}],
        ),
    ]
    tests = aggregate_ab_tests(rows, winner_by="views")
    edges = {(t["video_id"], t["partner_video_id"]) for t in tests}
    assert ("a", "b") in edges or ("b", "a") in {(a, b) for a, b in edges}
    assert len(tests) == 2  # a-b and a-c (c only lists partner a in fixture)


def test_winner_by_views():
    assert (
        winner_video_id(
            "a",
            "b",
            {"views": 100},
            {"views": 500},
            winner_by="views",
        )
        == "b"
    )


def test_cohort_medians():
    rows = [_row("x", 100, 10), _row("y", 300, 30)]
    med = cohort_medians(rows)
    assert med["views"] == 200.0
    assert saves_per_1k(rows[0]["metrics"]) == 100.0
