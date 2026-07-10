"""Unit tests for MCP component aggregation helpers (no Supabase)."""

from __future__ import annotations

from tools.video_components import _metric_value, _nested_get


def test_nested_get_hook_type():
    comp = {"hook": {"type": "warning"}, "funnel_stage": "TOFU"}
    assert _nested_get(comp, "hook.type") == "warning"
    assert _nested_get(comp, "funnel_stage") == "TOFU"


def test_metric_value_saves_per_1k():
    row = {"metrics": {"views": 1000, "saves": 20, "likes": 1, "comments": 0, "shares": 0}}
    assert _metric_value(row, "saves_per_1k") == 20.0
