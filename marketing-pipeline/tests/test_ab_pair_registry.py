"""Tests for variant group registry validation."""

import json
import pytest

from marketing_pipeline.tiktok.stages.ab_pair_registry import (
    load_registry_pairs,
    validate_registry_pairs,
)


def test_production_registry_groups_are_valid():
    entries = load_registry_pairs()
    assert len(entries) >= 6
    for entry in entries:
        assert 2 <= len(entry["video_ids"]) <= 4


def test_reject_single_video_group():
    errors = validate_registry_pairs(
        [
            {
                "pair_id": "bad",
                "video_ids": ["a"],
            }
        ]
    )
    assert any("2–4" in e for e in errors)


def test_reject_five_way_cluster():
    errors = validate_registry_pairs(
        [
            {
                "pair_id": "bad",
                "video_ids": ["a", "b", "c", "d", "e"],
            }
        ]
    )
    assert any("2–4" in e for e in errors)


def test_accept_three_way_cluster():
    errors = validate_registry_pairs(
        [
            {
                "pair_id": "triple",
                "video_ids": ["a", "b", "c"],
            }
        ]
    )
    assert errors == []


def test_reject_video_reuse_across_pairs():
    errors = validate_registry_pairs(
        [
            {"pair_id": "one", "video_ids": ["a", "b"]},
            {"pair_id": "two", "video_ids": ["b", "c"]},
        ]
    )
    assert any("already in group" in e for e in errors)


def test_load_registry_raises_on_invalid(tmp_path):
    bad = tmp_path / "ab_pair_registry.json"
    bad.write_text(
        json.dumps({"pairs": [{"pair_id": "x", "video_ids": ["1"]}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="2–4"):
        load_registry_pairs(bad)
