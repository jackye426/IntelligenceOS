"""Tests for carousel text fitting and PPTX build."""

from __future__ import annotations

from pathlib import Path

import pytest

from carousel.pptx_builder import CarouselContent, build_carousel_pptx, get_template, load_templates
from carousel.text_fit import fit_text_to_box


def test_load_five_templates() -> None:
    templates = load_templates()
    assert len(templates) == 5
    ids = {t["id"] for t in templates}
    assert "classic_blue" in ids
    assert "photo_body_left" in ids


def test_fit_text_shrinks_long_copy() -> None:
    long_text = (
        "Before you can explain it to a doctor, you need to understand it yourself. "
        "Take time to observe what is happening in your body and write it down."
    )
    short_fit = fit_text_to_box(
        "Short headline.",
        width_in=8.0,
        height_in=2.0,
        max_pt=50,
        min_pt=20,
        font_role="headline",
    )
    long_fit = fit_text_to_box(
        long_text,
        width_in=7.5,
        height_in=2.2,
        max_pt=20,
        min_pt=13,
        font_role="body",
    )
    assert short_fit.font_size_pt >= long_fit.font_size_pt
    assert short_fit.overflow is False


def test_build_pptx_all_slides(tmp_path: Path) -> None:
    content = CarouselContent(
        topic="Symptom tracking",
        template_id="classic_blue",
        hook="How to talk about your endo symptoms",
        hook_subtitle="so your GP can't ignore them",
        slides=[
            {"main_text": "Your GP appointment is 8 minutes.", "subtext": "Being prepared is key."},
            {"main_text": "First, work out your symptoms.", "subtext": "Observe what happens in your body."},
            {"main_text": "Is it cyclical?", "subtext": "Note what happens in relation to your cycle."},
        ],
        cta="Save this for your next appointment.",
        caption="Caption text here.\n\n#endometriosis #docmap",
    )
    out_path, metrics = build_carousel_pptx(content, out_dir=tmp_path)
    assert out_path.exists()
    assert out_path.suffix == ".pptx"
    # title + hook + 3 body + cta = 6 slides
    assert metrics["slide_count"] == 6
    assert metrics["template_id"] == "classic_blue"


def test_unknown_template_raises() -> None:
    with pytest.raises(ValueError, match="Unknown template_id"):
        get_template("not_a_template")
