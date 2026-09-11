"""Deterministic, reproducible deep-sample selection for a large catalog.

At ~1,372 posts the expensive stages (download, Whisper, OCR, components) cannot
run on everything, but "most recent N" would cover only the latest period and say
nothing about how the audience was built. This module:

1. splits the publish timeline into eras by detecting sustained shifts in the
   rolling median view count,
2. tiers each post against its *local* neighbours rather than the whole catalog,
3. draws a stratified sample across (era x tier) with a fixed seed,
4. writes `sample_plan.json` recording the eras, quotas, seed, selected ids and
   the catalog content hash.

Refresh, component extraction, sync and the manifest all read that file rather
than re-deriving a selection, so a conclusion can always be traced back to a
named, regenerable sample.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from datetime import datetime, timezone
from typing import Any

from marketing_pipeline import config

DEFAULT_SEED = 20260910
DEFAULT_DEEP = 200
MIN_ERA_POSTS = 25
MAX_ERAS = 3
ROLLING_WINDOW = 40
ERA_NAMES = ("era_1", "era_2", "era_3")


def _views(row: dict[str, Any]) -> float | None:
    raw = row.get("view_count")
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _ordered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Oldest first, ties broken by id so ordering is total and stable."""
    return sorted(
        (r for r in rows if r.get("video_id")),
        key=lambda r: (str(r.get("post_datetime_utc") or ""), str(r.get("video_id"))),
    )


def catalog_hash(rows: list[dict[str, Any]]) -> str:
    """Content hash over the fields the plan depends on."""
    payload = [
        [str(r.get("video_id")), str(r.get("post_datetime_utc") or ""), r.get("view_count")]
        for r in _ordered(rows)
    ]
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def rolling_medians(values: list[float | None], window: int = ROLLING_WINDOW) -> list[float | None]:
    """Centred rolling median; window slides inward at the edges."""
    total = len(values)
    out: list[float | None] = []
    for i in range(total):
        if total <= window:
            start, end = 0, total
        else:
            half = window // 2
            start = max(0, i - half)
            end = start + window
            if end > total:
                end, start = total, total - window
        present = [v for v in values[start:end] if v is not None]
        out.append(statistics.median(present) if present else None)
    return out


class _SegmentCost:
    """O(1) sum of squared deviations for any slice, via prefix sums.

    The boundary search evaluates O(n^2) candidate splits. Recomputing each
    segment's variance by slicing makes that O(n^3): fine on 400 synthetic rows,
    ~10^9 operations on a 1,372-post catalog. Prefix sums make each evaluation
    constant time, so the search stays sub-second at full scale.
    """

    def __init__(self, series: list[float]) -> None:
        self._sum = [0.0]
        self._sq = [0.0]
        for value in series:
            self._sum.append(self._sum[-1] + value)
            self._sq.append(self._sq[-1] + value * value)

    def __call__(self, start: int, end: int) -> float:
        n = end - start
        if n <= 0:
            return 0.0
        total = self._sum[end] - self._sum[start]
        squares = self._sq[end] - self._sq[start]
        # sum((x - mean)^2) == sum(x^2) - (sum x)^2 / n
        return max(squares - (total * total) / n, 0.0)


def detect_eras(rows: list[dict[str, Any]], *, max_eras: int = MAX_ERAS) -> list[dict[str, Any]]:
    """Split the timeline where the rolling view median shifts most.

    Exhaustive two-boundary search minimising within-era variance of the rolling
    median. Deterministic, and small enough at this catalog size.
    """
    ordered = _ordered(rows)
    total = len(ordered)
    if total == 0:
        return []

    med = rolling_medians([_views(r) for r in ordered])
    # Log scale: growth is multiplicative, and it keeps one viral post from
    # dominating the variance.
    series = [round(math.log10(max(v or 0.0, 1.0)), 6) for v in med]

    cost_of = _SegmentCost(series)

    if total < MIN_ERA_POSTS * 2 or max_eras < 2:
        bounds: list[int] = []
    elif total < MIN_ERA_POSTS * 3 or max_eras == 2:
        best, bounds = None, []
        for b in range(MIN_ERA_POSTS, total - MIN_ERA_POSTS + 1):
            cost = cost_of(0, b) + cost_of(b, total)
            if best is None or cost < best:
                best, bounds = cost, [b]
    else:
        best, bounds = None, []
        for b1 in range(MIN_ERA_POSTS, total - 2 * MIN_ERA_POSTS + 1):
            c1 = cost_of(0, b1)
            for b2 in range(b1 + MIN_ERA_POSTS, total - MIN_ERA_POSTS + 1):
                cost = c1 + cost_of(b1, b2) + cost_of(b2, total)
                if best is None or cost < best:
                    best, bounds = cost, [b1, b2]

    edges = [0, *bounds, total]
    names = ERA_NAMES if len(edges) - 1 == 3 else ERA_NAMES[: len(edges) - 1]
    eras: list[dict[str, Any]] = []
    for idx in range(len(edges) - 1):
        start, end = edges[idx], edges[idx + 1]
        span = ordered[start:end]
        present = [v for v in (_views(r) for r in span) if v is not None]
        eras.append(
            {
                "era": names[idx] if idx < len(names) else f"era_{idx + 1}",
                "index_start": start,
                "index_end": end,
                "posts": end - start,
                "from": span[0].get("post_datetime_utc") if span else None,
                "to": span[-1].get("post_datetime_utc") if span else None,
                "median_views": round(statistics.median(present), 1) if present else None,
                "view_floor": round(min(present), 1) if present else None,
                "views_coverage": len(present),
            }
        )
    return eras


def _local_tier(index: int, values: list[float | None], window: int = ROLLING_WINDOW) -> str:
    total = len(values)
    comparison_window = min(window + 1, total)
    if total <= comparison_window:
        start, end = 0, total
    else:
        half = comparison_window // 2
        start = max(0, index - half)
        end = start + comparison_window
        if end > total:
            end, start = total, total - comparison_window
    present = [v for j, v in enumerate(values[start:end], start=start) if j != index and v is not None]
    score = values[index]
    if score is None or len(present) < 12:
        return "unknown"
    med = statistics.median(present)
    if med <= 0:
        return "unknown"
    ratio = score / med
    if ratio >= 1.25:
        return "outperform"
    if ratio <= 0.75:
        return "underperform"
    return "typical"


def build_sample_plan(
    rows: list[dict[str, Any]],
    *,
    deep: int = DEFAULT_DEEP,
    seed: int = DEFAULT_SEED,
    account: str | None = None,
) -> dict[str, Any]:
    """Stratified (era x tier) sample. Same rows + same seed => same ids."""
    account = account or config.ACCOUNT
    ordered = _ordered(rows)
    total = len(ordered)
    eras = detect_eras(rows)
    views = [_views(r) for r in ordered]

    strata: dict[tuple[str, str], list[str]] = {}
    era_of: dict[str, str] = {}
    tier_of: dict[str, str] = {}
    for era in eras:
        for i in range(era["index_start"], era["index_end"]):
            vid = str(ordered[i]["video_id"])
            tier = _local_tier(i, views)
            era_of[vid] = era["era"]
            tier_of[vid] = tier
            strata.setdefault((era["era"], tier), []).append(vid)

    deep = min(deep, total)
    # Proportional allocation with a floor, so a small early era is never empty.
    quotas: dict[tuple[str, str], int] = {}
    if strata:
        floor = 1 if deep >= len(strata) else 0
        remaining = deep - floor * len(strata)
        sizes = {k: len(v) for k, v in strata.items()}
        pool = sum(sizes.values()) or 1
        for key, size in sizes.items():
            quotas[key] = min(size, floor + int(remaining * size / pool))
        # Hand out any rounding remainder largest-stratum first.
        leftover = deep - sum(quotas.values())
        ordered_keys = [key for key, _ in sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0]))]
        while leftover > 0:
            eligible = [key for key in ordered_keys if quotas[key] < sizes[key]]
            if not eligible:
                break
            for key in eligible:
                if leftover <= 0:
                    break
                quotas[key] += 1
                leftover -= 1

    selected: list[str] = []
    for key in sorted(strata):
        ids = sorted(strata[key])
        rng = random.Random(f"{seed}:{account}:{key[0]}:{key[1]}")
        rng.shuffle(ids)
        selected.extend(ids[: quotas.get(key, 0)])
    selected.sort()

    return {
        "account": account,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "deep_target": deep,
        "catalog_count": total,
        "catalog_hash": catalog_hash(rows),
        "rolling_window": ROLLING_WINDOW,
        "eras": eras,
        "quotas": {f"{e}|{t}": n for (e, t), n in sorted(quotas.items())},
        "stratum_sizes": {f"{e}|{t}": len(v) for (e, t), v in sorted(strata.items())},
        "deep_sample": selected,
        "deep_sample_count": len(selected),
        "era_of": era_of,
        "tier_of": tier_of,
    }


def save_sample_plan(plan: dict[str, Any]) -> str:
    path = config.SAMPLE_PLAN_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def load_sample_plan() -> dict[str, Any] | None:
    path = config.SAMPLE_PLAN_JSON
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def deep_sample_ids() -> set[str]:
    plan = load_sample_plan()
    return set(plan.get("deep_sample") or []) if plan else set()


def run_sample_plan(
    *,
    deep: int = DEFAULT_DEEP,
    seed: int = DEFAULT_SEED,
    since: str | None = None,
) -> dict[str, Any]:
    """CLI entry: read the catalog for the active account, write sample_plan.json."""
    from marketing_pipeline.tiktok.stages.collect_catalog import load_catalog

    rows = list(load_catalog(config.CATALOG_DIR).values())
    if since:
        rows = [r for r in rows if str(r.get("post_date_utc") or "") >= since]
    if not rows:
        return {
            "account": config.ACCOUNT,
            "error": f"No catalog rows found in {config.CATALOG_DIR}. Run fetch-catalog first.",
        }
    plan = build_sample_plan(rows, deep=deep, seed=seed)
    path = save_sample_plan(plan)
    return {
        "account": plan["account"],
        "catalog_count": plan["catalog_count"],
        "catalog_hash": plan["catalog_hash"],
        "deep_sample_count": plan["deep_sample_count"],
        "eras": [
            {k: e[k] for k in ("era", "posts", "from", "to", "median_views")} for e in plan["eras"]
        ],
        "sample_plan_path": path,
    }
