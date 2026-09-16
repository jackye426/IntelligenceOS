"""Server-side specialty boards. Exemplars are handles only."""

from __future__ import annotations

from statistics import median
from typing import Any

from marketing_pipeline.creators.store import get_store


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = int(round((len(ordered) - 1) * q))
    return float(ordered[idx])


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(median(values))


def _handles(profiles: list[dict[str, Any]], key: str, reverse: bool = True, n: int = 5) -> list[str]:
    ranked = [p for p in profiles if p.get(key) is not None]
    ranked.sort(key=lambda p: p.get(key) or 0, reverse=reverse)
    return [p["handle"] for p in ranked[:n]]


def rebuild_specialty_stats(*, store=None) -> dict[str, int]:
    store = store or get_store()
    profiles = [
        p
        for p in store.list("creator_profiles")
        if p.get("is_doctor") and p.get("stage") == "scored"
    ]
    by_key: dict[str, list[dict[str, Any]]] = {"_all": profiles}
    for p in profiles:
        key = p.get("specialty_key") or "unknown"
        by_key.setdefault(key, []).append(p)

    for key, group in by_key.items():
        followers = [float(p["follower_count"]) for p in group if p.get("follower_count") is not None]
        posts = [float(p["posts_30d"]) for p in group if p.get("posts_30d") is not None]
        saves = [float(p["median_saves_per_1k"]) for p in group if p.get("median_saves_per_1k") is not None]
        shares = [float(p["median_shares_per_1k"]) for p in group if p.get("median_shares_per_1k") is not None]
        vtf = [float(p["views_to_followers_median"]) for p in group if p.get("views_to_followers_median") is not None]
        durs = [float(p["median_duration_sec"]) for p in group if p.get("median_duration_sec") is not None]
        format_hist: dict[str, int] = {}
        cta_hist: dict[str, int] = {}
        hook_hist: dict[str, int] = {}
        for p in group:
            for k, n in (p.get("format_mix") or {}).items():
                format_hist[k] = format_hist.get(k, 0) + int(n)
            for k, n in (p.get("cta_mix") or {}).items():
                cta_hist[k] = cta_hist.get(k, 0) + int(n)
            for job in p.get("hook_jobs") or []:
                hook_hist[job] = hook_hist.get(job, 0) + 1
        uk_private = [
            p
            for p in group
            if (p.get("geo_country") or "").upper() == "GB"
            and p.get("practice_setting") in {"private", "mixed"}
        ]
        mid = [p for p in group if p.get("follower_count") and 5_000 <= int(p["follower_count"]) <= 100_000]
        vanity = [p for p in group if p.get("follower_count") and int(p["follower_count"]) > 250_000]
        store.upsert(
            "creator_specialty_stats",
            {
                "specialty_key": key,
                "n_doctors": len(group),
                "n_uk_private": len(uk_private),
                "n_deep_libraries": sum(1 for p in group if p.get("deep_status") not in {None, "none"}),
                "median_followers": _median(followers),
                "p25_followers": _pct(followers, 0.25),
                "p75_followers": _pct(followers, 0.75),
                "median_posts_30d": _median(posts),
                "median_saves_per_1k": _median(saves),
                "median_shares_per_1k": _median(shares),
                "median_views_to_followers": _median(vtf),
                "format_histogram": format_hist,
                "cta_histogram": cta_hist,
                "hook_job_histogram": hook_hist,
                "median_duration_sec": _median(durs),
                "exemplar_handles": {
                    "high_saves": _handles(group, "median_saves_per_1k"),
                    "high_efficiency": _handles(group, "views_to_followers_median"),
                    "mid_size": [p["handle"] for p in mid[:5]],
                    "uk_private": [p["handle"] for p in uk_private[:5]],
                    "contrast_vanity": [p["handle"] for p in vanity[:5]],
                },
            },
            keys=("specialty_key",),
        )
    return {"specialties": len(by_key), "doctors": len(profiles)}
