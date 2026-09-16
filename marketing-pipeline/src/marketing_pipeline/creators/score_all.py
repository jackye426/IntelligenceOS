"""Score every classified profile and write lane/scores back."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from marketing_pipeline.creators.score import follower_band, score_profile
from marketing_pipeline.creators.store import get_store


def score_all(*, store=None) -> dict[str, int]:
    store = store or get_store()
    profiles = [
        p
        for p in store.list("creator_profiles")
        if p.get("stage") in {"classified", "scored", "hydrated"}
    ]
    bands_vtf: dict[str, list[float]] = defaultdict(list)
    bands_saves: dict[str, list[float]] = defaultdict(list)
    for p in profiles:
        band = follower_band(p.get("follower_count"))
        if p.get("views_to_followers_median") is not None:
            bands_vtf[band].append(float(p["views_to_followers_median"]))
        if p.get("median_saves_per_1k") is not None:
            bands_saves[band].append(float(p["median_saves_per_1k"]))

    n = 0
    for p in profiles:
        band = follower_band(p.get("follower_count"))
        scored = score_profile(
            p,
            band_views_to_followers=bands_vtf.get(band),
            band_saves=bands_saves.get(band),
        )
        store.update(
            "creator_profiles",
            {
                "lane": scored["lane"],
                "lane_reasons": scored["lane_reasons"],
                "customer_score": scored["customer_score"],
                "research_score": scored["research_score"],
                "score_breakdown": scored["score_breakdown"],
                "score_coverage": scored["score_coverage"],
                "scoring_version": scored["scoring_version"],
                "good_fit": scored["good_fit"],
                "good_fit_version": scored["good_fit_version"],
                "stage": "scored",
                "work_status": "ready",
            },
            id=p["id"],
        )
        n += 1
    return {"scored": n}
