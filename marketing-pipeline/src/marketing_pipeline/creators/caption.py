"""Cheap caption opening proxy (not OCR)."""

from __future__ import annotations

import re

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def caption_hook(caption: str | None, *, max_chars: int = 80) -> str | None:
    text = (caption or "").strip()
    if not text:
        return None
    first = _SENTENCE_SPLIT.split(text, maxsplit=1)[0].strip()
    if len(first) <= max_chars:
        return first
    return first[:max_chars].rstrip()
