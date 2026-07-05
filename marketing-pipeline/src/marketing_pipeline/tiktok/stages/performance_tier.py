"""Compute performance tier vs cohort medians."""

from __future__ import annotations

import statistics
from typing import Any

from marketing_pipeline.tiktok.models import TikTokMarketingDataset


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def _tier(score: float, median: float) -> str:
    if median <= 0:
        return "typical"
    ratio = score / median
    if ratio >= 1.25:
        return "outperform"
    if ratio <= 0.75:
        return "underperform"
    return "typical"


def compute_performance_tiers(dataset: TikTokMarketingDataset) -> dict[str, dict[str, Any]]:
    views_list: list[float] = []
    saves_list: list[float] = []
    for record in dataset.videos.values():
        m = record.post.metrics
        views_list.append(float(m.views or 0))
        spk = m.saves_per_1k_views
        if spk is None and m.views and m.saves:
            spk = (m.saves / m.views) * 1000
        saves_list.append(float(spk or 0))

    med_views = _median(views_list)
    med_saves = _median(saves_list)

    tiers: dict[str, dict[str, Any]] = {}
    for video_id, record in dataset.videos.items():
        m = record.post.metrics
        views = float(m.views or 0)
        spk = m.saves_per_1k_views
        if spk is None and m.views and m.saves:
            spk = round((m.saves / m.views) * 1000, 2)
        spk_f = float(spk or 0)
        tiers[video_id] = {
            "views": _tier(views, med_views),
            "saves_per_1k": _tier(spk_f, med_saves),
            "cohort_median_views": round(med_views, 1),
            "cohort_median_saves_per_1k": round(med_saves, 2),
        }
    return tiers
