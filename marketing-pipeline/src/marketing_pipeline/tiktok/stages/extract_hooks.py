"""Extract spoken and caption hooks from parsed video data."""

from __future__ import annotations

import re

from marketing_pipeline.tiktok.models import TikTokHook


def first_sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    match = re.search(r"[.!?](?:\s|$)", text)
    if match:
        return text[: match.start() + 1].strip()
    return text.split("\n")[0].strip()[:200]


def first_line_of_caption(caption: str | None) -> str | None:
    if not caption:
        return None
    caption = caption.strip()
    match = re.search(r"[.!?](?:\s|$)", caption)
    if match and match.start() < 200:
        return caption[: match.start() + 1].strip()
    return caption.split("\n")[0].strip()[:200]


def extract_hook(
    video_id: str,
    *,
    spoken_hook: str | None,
    transcript: str | None,
    caption: str | None,
    onscreen_hook: str | None = None,
) -> TikTokHook:
    spoken = spoken_hook or (first_sentence(transcript) if transcript else None)
    caption_hook = first_line_of_caption(caption)

    hook_source = "spoken"
    if onscreen_hook:
        hook_source = "ocr"
    elif spoken:
        hook_source = "spoken"
    elif caption_hook:
        hook_source = "caption"

    return TikTokHook(
        video_id=video_id,
        spoken_hook=spoken or None,
        caption_hook=caption_hook,
        onscreen_hook=onscreen_hook,
        hook_source=hook_source,
        confidence=0.5 if onscreen_hook else 1.0,
    )


def resolve_primary_hook(hook: TikTokHook) -> str | None:
    if hook.onscreen_hook:
        return hook.onscreen_hook
    if hook.spoken_hook:
        return hook.spoken_hook
    return hook.caption_hook
