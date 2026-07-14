"""Auto-size and wrap text to fit PPTX text zones without overflow."""

from __future__ import annotations

import math
import re
import textwrap
from dataclasses import dataclass


_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class FitResult:
    font_size_pt: int
    text: str
    line_count: int
    overflow: bool


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip())


def _char_width_factor(font_role: str) -> float:
    """Approximate average character width as a fraction of font size (in points)."""
    if font_role in {"headline", "cta", "meta"}:
        return 0.52
    return 0.48


def _line_height_factor(font_role: str) -> float:
    if font_role in {"headline", "cta", "meta"}:
        return 1.15
    return 1.25


def _chars_per_line(*, width_in: float, font_size_pt: int, font_role: str) -> int:
    # 1 inch = 72 points; approximate glyph width in inches
    char_w_in = (font_size_pt / 72.0) * _char_width_factor(font_role)
    if char_w_in <= 0:
        return 40
    return max(8, int(width_in / char_w_in))


def _wrap_text(text: str, chars_per_line: int) -> list[str]:
    if not text:
        return [""]
    paragraphs = text.split("\n")
    lines: list[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            lines.append("")
            continue
        wrapped = textwrap.wrap(
            para,
            width=chars_per_line,
            break_long_words=False,
            break_on_hyphens=True,
        )
        lines.extend(wrapped or [""])
    return lines or [""]


def _line_height_in(font_size_pt: int, font_role: str) -> float:
    return (font_size_pt / 72.0) * _line_height_factor(font_role)


def fit_text_to_box(
    text: str,
    *,
    width_in: float,
    height_in: float,
    max_pt: int,
    min_pt: int,
    font_role: str = "body",
) -> FitResult:
    """
    Find the largest font size where wrapped text fits inside the box.
    Falls back to min_pt with aggressive wrapping if still too tall.
    """
    text = _normalize(text)
    if not text:
        return FitResult(font_size_pt=max_pt, text="", line_count=0, overflow=False)

    best_size = min_pt
    best_lines: list[str] = []
    overflow = True

    for size in range(max_pt, min_pt - 1, -1):
        cpl = _chars_per_line(width_in=width_in, font_size_pt=size, font_role=font_role)
        lines = _wrap_text(text, cpl)
        needed_h = len(lines) * _line_height_in(size, font_role)
        if needed_h <= height_in * 1.02:
            best_size = size
            best_lines = lines
            overflow = False
            break
        best_lines = lines

    if overflow and best_lines:
        # Last resort: tighten chars-per-line at min size
        cpl = max(6, _chars_per_line(width_in=width_in, font_size_pt=min_pt, font_role=font_role) - 4)
        best_lines = _wrap_text(text, cpl)
        best_size = min_pt
        needed_h = len(best_lines) * _line_height_in(min_pt, font_role)
        overflow = needed_h > height_in * 1.05

    return FitResult(
        font_size_pt=best_size,
        text="\n".join(best_lines),
        line_count=len(best_lines),
        overflow=overflow,
    )


def adjust_y_for_valign(
    *,
    y_in: float,
    box_h_in: float,
    line_count: int,
    font_size_pt: int,
    font_role: str,
    valign: str,
) -> float:
    """Shift text box vertically when content is shorter than the zone."""
    if line_count <= 0 or valign == "top":
        return y_in
    content_h = line_count * _line_height_in(font_size_pt, font_role)
    slack = max(0.0, box_h_in - content_h)
    if valign == "middle":
        return y_in + slack / 2.0
    if valign == "bottom":
        return y_in + slack
    return y_in


def estimate_slide_count_hint(main_text: str, subtext: str, *, width_in: float, height_in: float) -> dict[str, int | bool]:
    """Quick diagnostic for the writer — whether copy is likely too long."""
    main_fit = fit_text_to_box(
        main_text,
        width_in=width_in,
        height_in=height_in * 0.45,
        max_pt=50,
        min_pt=26,
        font_role="headline",
    )
    body_fit = fit_text_to_box(
        subtext,
        width_in=width_in,
        height_in=height_in * 0.55,
        max_pt=25,
        min_pt=14,
        font_role="body",
    )
    return {
        "main_font_pt": main_fit.font_size_pt,
        "body_font_pt": body_fit.font_size_pt,
        "main_overflow": main_fit.overflow,
        "body_overflow": body_fit.overflow,
        "main_lines": main_fit.line_count,
        "body_lines": body_fit.line_count,
    }
