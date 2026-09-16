"""Reconcile corpus counters for `creators status`."""

from __future__ import annotations

from collections import Counter
from typing import Any

from marketing_pipeline.creators.store import get_store


def corpus_status(*, store=None) -> dict[str, Any]:
    store = store or get_store()
    profiles = store.list("creator_profiles")
    stages = Counter(p.get("stage") or "unknown" for p in profiles)
    lanes = Counter(p.get("lane") or "none" for p in profiles)
    deep = Counter(p.get("deep_status") or "none" for p in profiles)
    runs = store.list("creator_crawl_runs")
    runs.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    return {
        "profiles": len(profiles),
        "by_stage": dict(stages),
        "by_lane": dict(lanes),
        "by_deep_status": dict(deep),
        "good_fit": sum(1 for p in profiles if p.get("good_fit")),
        "videos": store.count("creator_videos") if hasattr(store, "count") else len(store.list("creator_videos")),
        "insight_cards": len(store.list("creator_insight_cards")),
        "last_runs": [
            {
                "id": r.get("id"),
                "command": r.get("command"),
                "status": r.get("status"),
                "counters": r.get("counters"),
                "started_at": r.get("started_at"),
            }
            for r in runs[:10]
        ],
    }
