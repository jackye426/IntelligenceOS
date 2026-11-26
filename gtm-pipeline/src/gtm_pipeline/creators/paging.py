"""Paged Supabase reads used by creator link/promote."""

from __future__ import annotations

from typing import Any, Callable


def fetch_all(
    query_factory: Callable[..., Any],
    *,
    page: int = 1000,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Walk `.range` until a short page. `query_factory` must return a fresh query."""
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        remaining = None if limit is None else max(limit - len(rows), 0)
        if remaining == 0:
            return rows
        take = page if remaining is None else min(page, remaining)
        batch = query_factory().range(offset, offset + take - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < take:
            return rows
        offset += take
