"""Resolve posted_at from catalog (preferred) or master transcript fallback."""

from __future__ import annotations

from typing import Any


def resolve_posted_at(
    video_id: str,
    *,
    catalog_entry: dict[str, Any] | None,
    parsed_posted_at: str | None,
) -> str | None:
    if catalog_entry:
        dt = catalog_entry.get("post_datetime_utc")
        if dt:
            return str(dt)
    return parsed_posted_at
