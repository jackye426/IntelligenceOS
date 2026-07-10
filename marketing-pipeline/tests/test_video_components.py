"""Tests for video component schema and store (no LLM)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marketing_pipeline.tiktok.stages.video_components_models import VideoComponents
from marketing_pipeline.tiktok.stages.video_components_store import (
    rebuild_index,
    save_components,
)


def _card(**overrides) -> dict:
    base = {
        "video_id": "test-vid",
        "length_sec": 60,
        "hook": {
            "text": "Do you think you have endometriosis?",
            "channel": "spoken",
            "type": "direct_question",
            "specificity": "medium",
            "creates_curiosity": True,
            "contradicts_common_belief": False,
            "payoff_clear": True,
            "seconds_to_main_claim": 3.0,
        },
        "main_claim": {"text": "You can see a CNS online."},
        "supporting_explanation": {"summary": "Liz explains CNS access."},
        "funnel_stage": "BOFU",
        "funnel_rationale": "Booking CTA for specialist",
        "cta": {
            "present": True,
            "wording": "link in bio",
            "position": "caption",
            "channel": "caption",
            "explicitness": "explicit",
            "requested_action_raw": "book",
            "urgency": "soft",
            "funnel_stage": "BOFU",
        },
        "topic": {"primary_raw": "CNS booking", "secondary_raw": []},
        "speaker": {"primary_raw": "Liz", "type_raw": "clinician"},
        "format_raw": "expert_monologue",
        "caption_analysis": {"should": "be wiped"},
        "extraction": {
            "method": "batch_llm_v1",
            "confidence": 0.7,
            "needs_review": False,
            "inputs_hash": "abc",
        },
    }
    base.update(overrides)
    return base


def test_schema_forces_caption_analysis_null():
    card = VideoComponents.model_validate(_card())
    assert card.caption_analysis is None
    assert card.funnel_stage == "BOFU"
    assert card.hook.type == "direct_question"


def test_cta_absent_valid():
    data = _card()
    data["cta"] = {
        "present": False,
        "position": "none",
        "channel": "none",
        "explicitness": "none",
        "urgency": "none",
    }
    data["funnel_stage"] = "TOFU"
    card = VideoComponents.model_validate(data)
    assert card.cta.present is False


def test_hook_type_other_gets_note():
    data = _card()
    data["hook"]["type"] = "other"
    data["hook"]["type_other"] = None
    card = VideoComponents.model_validate(data)
    assert card.hook.type_other == "unspecified"


def test_invalid_hook_type_rejected():
    data = _card()
    data["hook"]["type"] = "not_a_real_type"
    with pytest.raises(Exception):
        VideoComponents.model_validate(data)


def test_funnel_stages():
    for stage in ("TOFU", "MOFU", "BOFU", "unclear"):
        data = _card(funnel_stage=stage)
        assert VideoComponents.model_validate(data).funnel_stage == stage


def test_sidecar_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import marketing_pipeline.tiktok.stages.video_components_store as store

    monkeypatch.setattr(store, "COMPONENTS_DIR", tmp_path)
    monkeypatch.setattr(store, "INDEX_PATH", tmp_path / "video_components_index.json")
    card = VideoComponents.model_validate(_card(video_id="sidecartest"))
    path = save_components(card)
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["caption_analysis"] is None
    index = rebuild_index()
    assert index["count"] == 1
    assert "sidecartest" in index["videos"]
