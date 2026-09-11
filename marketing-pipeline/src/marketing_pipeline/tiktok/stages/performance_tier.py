"""Compute performance tier vs cohort medians.

Two modes:

* **global** — median across the whole dataset. Fine for a small, young library
  like DocMap's (~70 posts, months old).
* **rolling** — median of each post's nearest neighbours in publish time. Required
  for a multi-year peer catalog, where a global median mostly ranks posts by how
  long they have been live rather than how well they did.

Missing metrics are `None`, never `0.0`. A zero would be counted as a real
measurement and drag the median down; an absent `save_count` on a public peer
catalog would otherwise collapse the saves median and mislabel the library.
"""

from __future__ import annotations

import statistics
from typing import Any

from marketing_pipeline.tiktok.models import TikTokMarketingDataset

# Centred window: 20 earlier + 20 later neighbours.
ROLLING_WINDOW = 40
# Below this many neighbours a ratio is not meaningful; report it as such.
MIN_WINDOW = 12

INSUFFICIENT = "insufficient_window"


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def _median_opt(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return statistics.median(present) if present else None


def _tier(score: float | None, median: float | None) -> str:
    if score is None or median is None or median <= 0:
        return "typical"
    ratio = score / median
    if ratio >= 1.25:
        return "outperform"
    if ratio <= 0.75:
        return "underperform"
    return "typical"


def _saves_per_1k(metrics: Any) -> float | None:
    """None when saves are unavailable — distinct from a genuine zero."""
    spk = metrics.saves_per_1k_views
    if spk is not None:
        return float(spk)
    if metrics.saves is None or not metrics.views:
        return None
    return round((metrics.saves / metrics.views) * 1000, 2)


def _views(metrics: Any) -> float | None:
    return None if metrics.views is None else float(metrics.views)


def compute_performance_tiers(dataset: TikTokMarketingDataset) -> dict[str, dict[str, Any]]:
    """Global-median tiers (DocMap default)."""
    views_list = [_views(r.post.metrics) for r in dataset.videos.values()]
    saves_list = [_saves_per_1k(r.post.metrics) for r in dataset.videos.values()]

    med_views = _median_opt(views_list)
    med_saves = _median_opt(saves_list)

    tiers: dict[str, dict[str, Any]] = {}
    for video_id, record in dataset.videos.items():
        m = record.post.metrics
        tiers[video_id] = {
            "views": _tier(_views(m), med_views),
            "saves_per_1k": _tier(_saves_per_1k(m), med_saves),
            "cohort_median_views": round(med_views, 1) if med_views is not None else None,
            "cohort_median_saves_per_1k": round(med_saves, 2) if med_saves is not None else None,
            "basis": "global",
        }
    return tiers


def _neighbour_slice(index: int, total: int, window: int) -> tuple[int, int]:
    """Centred window that slides inward at the edges instead of shrinking.

    The first and last posts are still compared against `window` neighbours, so
    an early breakout is not measured against a handful of posts.
    """
    if total <= window:
        return 0, total
    half = window // 2
    start = index - half
    if start < 0:
        start = 0
    end = start + window
    if end > total:
        end = total
        start = total - window
    return start, end


def compute_rolling_tiers(
    dataset: TikTokMarketingDataset,
    *,
    window: int = ROLLING_WINDOW,
    min_window: int = MIN_WINDOW,
) -> dict[str, dict[str, Any]]:
    """Tiers vs a rolling local median in publish-time order.

    Computed over the whole dataset, never a filtered subset, so a date filter
    cannot move a post's tier.
    """
    ordered = sorted(
        dataset.videos.items(),
        key=lambda kv: (kv[1].post.posted_at or "", kv[0]),
    )
    total = len(ordered)
    views_seq = [_views(r.post.metrics) for _, r in ordered]
    saves_seq = [_saves_per_1k(r.post.metrics) for _, r in ordered]

    tiers: dict[str, dict[str, Any]] = {}
    for i, (video_id, record) in enumerate(ordered):
        start, end = _neighbour_slice(i, total, min(window + 1, total))
        win_views = [value for j, value in enumerate(views_seq[start:end], start=start) if j != i]
        win_saves = [value for j, value in enumerate(saves_seq[start:end], start=start) if j != i]
        n_present = sum(1 for v in win_views if v is not None)

        med_views = _median_opt(win_views)
        med_saves = _median_opt(win_saves)
        score_views = views_seq[i]
        score_saves = saves_seq[i]

        if n_present < min_window:
            tiers[video_id] = {
                "views": INSUFFICIENT,
                "saves_per_1k": INSUFFICIENT,
                "views_ratio": None,
                "saves_per_1k_ratio": None,
                "window_n": n_present,
                "window_from": ordered[start][1].post.posted_at,
                "window_to": ordered[end - 1][1].post.posted_at,
                "basis": "rolling",
            }
            continue

        tiers[video_id] = {
            "views": "unknown" if score_views is None else _tier(score_views, med_views),
            "saves_per_1k": (
                "unknown" if score_saves is None else _tier(score_saves, med_saves)
            ),
            "views_ratio": (
                round(score_views / med_views, 3)
                if score_views is not None and med_views
                else None
            ),
            "saves_per_1k_ratio": (
                round(score_saves / med_saves, 3)
                if score_saves is not None and med_saves
                else None
            ),
            "local_median_views": round(med_views, 1) if med_views is not None else None,
            "local_median_saves_per_1k": round(med_saves, 2) if med_saves is not None else None,
            "window_n": n_present,
            "window_from": ordered[start][1].post.posted_at,
            "window_to": ordered[end - 1][1].post.posted_at,
            "basis": "rolling",
        }
    return tiers


def compute_tiers(
    dataset: TikTokMarketingDataset,
    *,
    basis: str = "global",
) -> dict[str, dict[str, Any]]:
    """Dispatch on basis. Peer libraries should always pass basis='rolling'."""
    if basis == "rolling":
        return compute_rolling_tiers(dataset)
    return compute_performance_tiers(dataset)
