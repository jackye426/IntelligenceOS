"""Tests for constitution amendment helpers."""

from __future__ import annotations

from pathlib import Path

from tools.constitution_amendments import append_bullet_to_markdown, append_bullet_to_section


def test_append_bullet_to_markdown_creates_section() -> None:
    updated, added = append_bullet_to_markdown(
        "Intro line.\n",
        section_title="Hook & packaging rules (from approved A/B learnings)",
        bullet="Prefer imperative hooks over soft interview opens.",
    )
    assert added is True
    assert "Prefer imperative hooks" in updated
    assert "## Hook & packaging rules" in updated


def test_append_bullet_creates_section(tmp_path: Path) -> None:
    path = tmp_path / "viral-format.md"
    path.write_text("Intro line.\n", encoding="utf-8")
    added = append_bullet_to_section(
        path,
        section_title="Hook & packaging rules (from approved A/B learnings)",
        bullet="Prefer imperative hooks over soft interview opens.",
    )
    assert added is True
    text = path.read_text(encoding="utf-8")
    assert "Prefer imperative hooks" in text
    assert "## Hook & packaging rules" in text


def test_append_bullet_deduplicates(tmp_path: Path) -> None:
    path = tmp_path / "viral-format.md"
    path.write_text(
        "## Anti-patterns\n\n- Soft interview open without a patient action in the first seconds.\n",
        encoding="utf-8",
    )
    added = append_bullet_to_section(
        path,
        section_title="Anti-patterns",
        bullet="Soft interview open without a patient action in the first seconds.",
    )
    assert added is False
    assert path.read_text(encoding="utf-8").count("- Soft interview") == 1


def test_append_bullet_under_existing_section(tmp_path: Path) -> None:
    path = tmp_path / "viral-format.md"
    path.write_text(
        "## Anti-patterns\n\n- First rule.\n\n## Other\n\nBody.\n",
        encoding="utf-8",
    )
    append_bullet_to_section(path, section_title="Anti-patterns", bullet="Second rule.")
    text = path.read_text(encoding="utf-8")
    assert "- First rule." in text
    assert "- Second rule." in text
    assert text.index("- Second rule.") < text.index("## Other")
