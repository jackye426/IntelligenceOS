"""Deep-job helpers. Stale window is 4h — never reuse GTM's 600s reclaim."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# GTM durable jobs reclaim at 600s. Whisper of ~80 clips is hours; reclaiming
# mid-job double-downloads media. Keep this constant wired to sql/014 default.
DEEP_STALE_SECONDS = 14400
GTM_STALE_SECONDS = 600

LISTING_PAUSE_START_MINUTES = 2 * 60 + 50  # 02:50 UTC
LISTING_PAUSE_END_MINUTES = 4 * 60 + 15  # 04:15 UTC


def listing_paused(now: datetime | None = None) -> bool:
    """DocMap TikTok cron owns the IP around 03:30 UTC."""
    now = now or datetime.now(timezone.utc)
    minutes = now.hour * 60 + now.minute
    return LISTING_PAUSE_START_MINUTES <= minutes < LISTING_PAUSE_END_MINUTES


def claim_order(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Priority desc, then created_at. Mirrors creator_claim_deep_job_items."""
    return sorted(
        items,
        key=lambda item: (
            -int(item.get("priority") or 0),
            str(item.get("created_at") or ""),
        ),
    )
