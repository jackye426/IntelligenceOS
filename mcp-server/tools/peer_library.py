"""Peer-library reads: a large observed catalog Claude analyses itself.

Design rules, in order of importance:

1. **Isolation.** Every read here requires an explicit account and refuses
   `docmap`. Peer evidence must never arrive through a DocMap-shaped tool, and
   DocMap tools must never serve peer rows.
2. **Context budget.** A 1,372-post catalog cannot ship with captions attached
   (~200-350 tokens/row). The manifest is lean by default; captions and
   transcripts come through the batch tool for a bounded id list. Every
   paginated response reports total, returned and cursor so truncation is
   visible rather than silent.
3. **Measure, do not conclude.** These tools compute dates, gaps, durations,
   ratios, rolling medians and coverage. They do not decide what a hook is
   doing, why a post worked, or which mechanics are portable. Component labels
   ride along marked as derived annotations that Claude may disagree with.
"""

from __future__ import annotations

import json
import math
import statistics
from typing import Any

from common.audit import log_tool_call
from tools.corpus_store import get_corpus
from tools.tiktok_shared import (
    account_scope_enforced,
    cadence_fields,
    comments_per_1k,
    fetch_tiktok_posts,
    rolling_local_stats,
    saves_per_1k,
    shares_per_1k,
)

MAX_BATCH = 25
MAX_MANIFEST_PAGE = 400
MIN_ERA_POSTS = 25
ERA_NAMES = ("era_1", "era_2", "era_3")

NOT_MEASURABLE = {
    "follower_time_series": "Not available. Public data shows no follower history.",
    "traffic_sources": "Not available. No paid/organic or For You vs follow split.",
    "retention": "Not available. Average watch time and finish rate are owner-only Studio metrics.",
    "demographics": "Not available for a peer account.",
    "conversions": "Not available. No link clicks or bookings.",
    "growth_causation": (
        "Views are cross-sectional: they measure how a post landed on the audience "
        "that already existed, not how many followers it added. Treat a rising view "
        "floor as a proxy, never as proof."
    ),
    "pacing_and_edit_rhythm": (
        "Not in evidence. OCR covers opening frames only, so mid-video captioning "
        "and edit rhythm cannot be assessed."
    ),
}


class PeerAccountError(ValueError):
    """Raised when a peer tool is called without a real peer account."""


def _require_peer(account: str | None) -> str:
    handle = (account or "").strip().lstrip("@").lower()
    if not handle:
        raise PeerAccountError("account is required, e.g. account='drleewarren'.")
    if handle == "docmap":
        raise PeerAccountError(
            "docmap is the owned library, not a peer. Use the get_tiktok_* tools for it."
        )
    return handle


# Ceiling on one corpus read. Rolling medians and era boundaries are only valid
# over the WHOLE catalog, so hitting this would silently change every ratio.
MAX_CORPUS_ROWS = 5000


def _all_rows(account: str) -> list[dict[str, Any]]:
    """Whole peer catalog. Rolling stats and eras must see every post."""
    return fetch_tiktok_posts(limit=MAX_CORPUS_ROWS, account=account)


def _corpus_truncated(rows: list[dict[str, Any]]) -> bool:
    return len(rows) >= MAX_CORPUS_ROWS


def _truncation_warning(rows: list[dict[str, Any]]) -> str | None:
    if not _corpus_truncated(rows):
        return None
    return (
        f"Catalog read hit the {MAX_CORPUS_ROWS}-row ceiling. Rolling medians and era "
        "boundaries are computed over the whole catalog, so these figures are "
        "UNRELIABLE until the ceiling is raised. Do not cite them."
    )


def _ordered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda r: (str(r.get("posted_at") or ""), str(r.get("platform_post_id"))),
    )


def _views(row: dict[str, Any]) -> float | None:
    value = (row.get("metrics") or {}).get("views")
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _num_or_none(value: Any) -> Any:
    """Blank strings are not data. Keep null distinct from zero."""
    return None if value in (None, "") else value


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


def _rolling_median_series(values: list[float | None], window: int = 40) -> list[float]:
    total = len(values)
    out: list[float] = []
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
        out.append(statistics.median(present) if present else 0.0)
    return out


def detect_eras(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split the timeline where the rolling view median shifts most.

    Same method as the pipeline's sample planner: minimise within-era variance of
    the log rolling median over at most two boundaries. Deterministic.
    """
    ordered = _ordered(rows)
    total = len(ordered)
    if total == 0:
        return []

    med = _rolling_median_series([_views(r) for r in ordered])
    series = [round(math.log10(max(v, 1.0)), 6) for v in med]

    cost_of = _SegmentCost(series)

    if total < MIN_ERA_POSTS * 2:
        bounds: list[int] = []
    elif total < MIN_ERA_POSTS * 3:
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
        durations = [
            d
            for d in ((r.get("metrics") or {}).get("duration_sec") for r in span)
            if isinstance(d, (int, float))
        ]
        eras.append(
            {
                "era": names[idx] if idx < len(names) else f"era_{idx + 1}",
                "label_status": "neutral_statistical_segment",
                "posts": end - start,
                "from": str(span[0].get("posted_at") or "")[:10] if span else None,
                "to": str(span[-1].get("posted_at") or "")[:10] if span else None,
                "median_views": round(statistics.median(present), 1) if present else None,
                "view_floor": round(min(present), 1) if present else None,
                "view_ceiling": round(max(present), 1) if present else None,
                "views_coverage": len(present),
                "median_duration_sec": round(statistics.median(durations), 1) if durations else None,
                "_start": start,
                "_end": end,
            }
        )
    return eras


def _monthly_trend(rows: list[dict[str, Any]], era_map: dict[str, str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        month = str(row.get("posted_at") or "")[:7]
        if month:
            grouped.setdefault(month, []).append(row)

    trend: list[dict[str, Any]] = []
    for month, month_rows in sorted(grouped.items()):
        views = [value for value in (_views(row) for row in month_rows) if value is not None]
        durations = [
            float(value)
            for value in ((row.get("metrics") or {}).get("duration_sec") for row in month_rows)
            if isinstance(value, (int, float))
        ]
        era_counts: dict[str, int] = {}
        for row in month_rows:
            era = era_map.get(str(row.get("platform_post_id")))
            if era:
                era_counts[era] = era_counts.get(era, 0) + 1
        dominant_era = max(era_counts, key=era_counts.get) if era_counts else None
        trend.append(
            {
                "month": month,
                "posts": len(month_rows),
                "median_views": round(statistics.median(views), 1) if views else None,
                "view_floor": round(min(views), 1) if views else None,
                "view_ceiling": round(max(views), 1) if views else None,
                "views_coverage": len(views),
                "median_duration_sec": (
                    round(statistics.median(durations), 1) if durations else None
                ),
                "statistical_era": dominant_era,
            }
        )
    return trend


def _isolation_audit(account: str, peer_rows: list[dict[str, Any]]) -> dict[str, Any]:
    docmap_rows = _all_rows("docmap")

    def wrong_url(rows: list[dict[str, Any]], expected: str) -> list[str]:
        marker = f"/@{expected}/"
        return [
            str(row.get("platform_post_id"))
            for row in rows
            if row.get("post_url") and marker not in str(row.get("post_url"))
        ]

    peer_ids = {str(row.get("platform_post_id")) for row in peer_rows}
    docmap_ids = {str(row.get("platform_post_id")) for row in docmap_rows}
    peer_wrong = wrong_url(peer_rows, account)
    docmap_wrong = wrong_url(docmap_rows, "docmap")
    overlaps = sorted(peer_ids & docmap_ids)
    passed = not peer_wrong and not docmap_wrong and not overlaps
    return {
        "status": "pass" if passed else "fail",
        "peer_account": account,
        "peer_rows": len(peer_rows),
        "docmap_rows": len(docmap_rows),
        "peer_rows_with_wrong_url": peer_wrong[:20],
        "docmap_rows_with_wrong_url": docmap_wrong[:20],
        "overlapping_video_ids": overlaps[:20],
        "safe_to_analyse": passed and account_scope_enforced(),
    }


def _era_of(rows: list[dict[str, Any]]) -> dict[str, str]:
    ordered = _ordered(rows)
    out: dict[str, str] = {}
    for era in detect_eras(rows):
        for i in range(era["_start"], era["_end"]):
            out[str(ordered[i].get("platform_post_id"))] = era["era"]
    return out


def _manifest_row(
    row: dict[str, Any],
    *,
    rolling: dict[str, Any],
    cadence: dict[str, Any],
    era: str | None,
    include_captions: bool,
) -> dict[str, Any]:
    metrics = row.get("metrics") or {}
    meta = row.get("metadata") or {}
    vid = str(row.get("platform_post_id"))
    item: dict[str, Any] = {
        "video_id": vid,
        "posted_at": row.get("posted_at"),
        "duration_sec": _num_or_none(metrics.get("duration_sec")),
        "views": _num_or_none(metrics.get("views")),
        "likes": _num_or_none(metrics.get("likes")),
        "comments": _num_or_none(metrics.get("comments")),
        "shares": _num_or_none(metrics.get("shares")),
        "saves": _num_or_none(metrics.get("saves")),
        "saves_per_1k_views": saves_per_1k(metrics) if metrics.get("saves") is not None else None,
        "comments_per_1k_views": (
            comments_per_1k(metrics) if metrics.get("comments") is not None else None
        ),
        "shares_per_1k_views": (
            shares_per_1k(metrics) if metrics.get("shares") is not None else None
        ),
        "era": era,
        "local_views_ratio": rolling.get("views_ratio"),
        "local_tier": rolling.get("tier"),
        "local_median_views": rolling.get("local_median_views"),
        "window_n": rolling.get("window_n"),
        "days_since_previous_post": cadence.get("days_since_previous_post"),
        "posts_in_same_week": cadence.get("posts_in_same_week"),
        "has_transcript": bool(row.get("transcript")),
        "has_components": isinstance(meta.get("components"), dict),
        "is_catalog_stub": bool(meta.get("is_catalog_stub")),
        "is_deep_sample": bool((meta.get("sample_plan") or {}).get("is_deep_sample")),
        "sample_plan_seed": (meta.get("sample_plan") or {}).get("seed"),
        "sample_plan_catalog_hash": (meta.get("sample_plan") or {}).get("catalog_hash"),
    }
    if include_captions:
        item["caption"] = row.get("caption")
        item["title"] = row.get("title")
    return item


def get_peer_corpus_manifest(
    account: str,
    *,
    cursor: int = 0,
    limit: int = MAX_MANIFEST_PAGE,
    include_captions: bool = False,
    video_ids: list[str] | None = None,
    sample_only: bool = False,
    order: str = "posted_at",
) -> dict[str, Any]:
    """Lean, complete map of a peer catalog.

    No captions or titles by default: at ~1,372 posts they alone would consume
    most of a context window. Ask for them with a bounded video_ids list, or
    pull full text through get_peer_content_batch.
    """
    handle = _require_peer(account)
    summary = f"account={handle} cursor={cursor} limit={limit} captions={include_captions}"
    try:
        rows = _all_rows(handle)
        if include_captions and not video_ids:
            raise PeerAccountError(
                "include_captions requires an explicit video_ids list (context budget). "
                "Use get_peer_content_batch for full text."
            )

        rolling = rolling_local_stats(rows)
        cadence = cadence_fields(rows)
        eras = _era_of(rows)

        ordered = _ordered(rows)
        if order == "views":
            ordered = sorted(ordered, key=lambda r: _views(r) or 0.0, reverse=True)
        elif order == "local_ratio":
            ordered = sorted(
                ordered,
                key=lambda r: rolling.get(str(r.get("platform_post_id")), {}).get("views_ratio")
                or 0.0,
                reverse=True,
            )

        if video_ids:
            wanted = {str(v) for v in video_ids}
            ordered = [r for r in ordered if str(r.get("platform_post_id")) in wanted]
        if sample_only:
            ordered = [
                row
                for row in ordered
                if ((row.get("metadata") or {}).get("sample_plan") or {}).get(
                    "is_deep_sample"
                )
            ]

        total = len(ordered)
        limit = max(1, min(limit, MAX_MANIFEST_PAGE))
        page = ordered[cursor : cursor + limit]
        items = [
            _manifest_row(
                r,
                rolling=rolling.get(str(r.get("platform_post_id")), {}),
                cadence=cadence.get(str(r.get("platform_post_id")), {}),
                era=eras.get(str(r.get("platform_post_id"))),
                include_captions=include_captions,
            )
            for r in page
        ]
        next_cursor = cursor + len(page)

        result = {
            "account": handle,
            "account_scope_enforced": account_scope_enforced(),
            "corpus_truncated": _corpus_truncated(rows),
            "corpus_truncation_warning": _truncation_warning(rows),
            "total_rows": total,
            "returned_rows": len(items),
            "cursor": cursor,
            "next_cursor": next_cursor if next_cursor < total else None,
            "has_more": next_cursor < total,
            "captions_included": include_captions,
            "sample_only": sample_only,
            "ordering": order,
            "field_coverage": {
                "views": sum(1 for i in items if i["views"] is not None),
                "duration_sec": sum(1 for i in items if i["duration_sec"] is not None),
                "saves": sum(1 for i in items if i["saves"] is not None),
                "transcript": sum(1 for i in items if i["has_transcript"]),
                "components": sum(1 for i in items if i["has_components"]),
            },
            "posts": items,
            "note": (
                "Lean rows: no captions or transcripts. Ratios are vs a rolling local "
                "median (window_n neighbours), not the catalog median. Missing metrics "
                "are null, never zero."
            ),
        }
        log_tool_call(
            tool_name="get_peer_corpus_manifest",
            request_summary=summary,
            success=True,
            entity_type="peer_library",
            entity_id=handle,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_peer_corpus_manifest",
            request_summary=summary,
            success=False,
            entity_type="peer_library",
            entity_id=str(account),
            error=str(exc),
        )
        raise


def get_peer_era_summary(account: str) -> dict[str, Any]:
    """Server-side aggregates, so eras can be read without 1,372 captions."""
    handle = _require_peer(account)
    summary = f"account={handle}"
    try:
        rows = _all_rows(handle)
        eras = [{k: v for k, v in e.items() if not k.startswith("_")} for e in detect_eras(rows)]
        era_map = _era_of(rows)

        by_month: dict[str, int] = {}
        durations: list[float] = []
        for row in rows:
            posted = str(row.get("posted_at") or "")[:7]
            if posted:
                by_month[posted] = by_month.get(posted, 0) + 1
            d = (row.get("metrics") or {}).get("duration_sec")
            if isinstance(d, (int, float)):
                durations.append(float(d))

        buckets = {"0-15s": 0, "16-30s": 0, "31-60s": 0, "61-180s": 0, "180s+": 0}
        for d in durations:
            if d <= 15:
                buckets["0-15s"] += 1
            elif d <= 30:
                buckets["16-30s"] += 1
            elif d <= 60:
                buckets["31-60s"] += 1
            elif d <= 180:
                buckets["61-180s"] += 1
            else:
                buckets["180s+"] += 1

        gaps = [
            c["days_since_previous_post"]
            for c in cadence_fields(rows).values()
            if c.get("days_since_previous_post") is not None
        ]

        result = {
            "account": handle,
            "account_scope_enforced": account_scope_enforced(),
            "corpus_truncated": _corpus_truncated(rows),
            "corpus_truncation_warning": _truncation_warning(rows),
            "catalog_size": len(rows),
            "eras": eras,
            "monthly_trend": _monthly_trend(rows, era_map),
            "posts_per_month": dict(sorted(by_month.items())),
            "duration_distribution": buckets,
            "duration_coverage": len(durations),
            "median_days_between_posts": round(statistics.median(gaps), 2) if gaps else None,
            "not_measurable": NOT_MEASURABLE,
            "note": (
                "Measurements only. era_1/era_2/era_3 are neutral statistical segments "
                "from shifts in rolling median views, not claims that a segment is the "
                "breakout or mature phase. Inspect monthly_trend and the underlying posts "
                "before naming what happened."
            ),
        }
        log_tool_call(
            tool_name="get_peer_era_summary",
            request_summary=summary,
            success=True,
            entity_type="peer_library",
            entity_id=handle,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_peer_era_summary",
            request_summary=summary,
            success=False,
            entity_type="peer_library",
            entity_id=str(account),
            error=str(exc),
        )
        raise


def get_peer_content_batch(
    account: str,
    video_ids: list[str],
    *,
    include_transcript: bool = True,
    include_components: bool = True,
) -> dict[str, Any]:
    """Full evidence for 1-25 posts per call: caption, transcript, hooks, OCR.

    Batched deliberately: reading a 200-post deep sample one tool call at a time
    burns the context on protocol overhead.
    """
    handle = _require_peer(account)
    summary = f"account={handle} n={len(video_ids or [])}"
    try:
        if not video_ids:
            raise PeerAccountError("video_ids is required. Select ids from the manifest.")
        if len(video_ids) > MAX_BATCH:
            raise PeerAccountError(
                f"Batch limit is {MAX_BATCH} videos ({len(video_ids)} requested). "
                "Split into consecutive calls."
            )

        rows = _all_rows(handle)
        rolling = rolling_local_stats(rows)
        cadence = cadence_fields(rows)
        eras = _era_of(rows)
        by_id = {str(r.get("platform_post_id")): r for r in rows}

        packets: list[dict[str, Any]] = []
        missing: list[str] = []
        for vid in [str(v) for v in video_ids]:
            row = by_id.get(vid)
            if not row:
                missing.append(vid)
                continue
            meta = row.get("metadata") or {}
            hook_detail = meta.get("hook_detail") or {}
            components = meta.get("components") if isinstance(meta.get("components"), dict) else None
            packet: dict[str, Any] = {
                "video_id": vid,
                "post_url": row.get("post_url"),
                "posted_at": row.get("posted_at"),
                "era": eras.get(vid),
                "duration_sec": _num_or_none((row.get("metrics") or {}).get("duration_sec")),
                "format": row.get("format"),
                "caption": row.get("caption"),
                "title": row.get("title"),
                "hook": row.get("hook"),
                "hook_source": hook_detail.get("hook_source"),
                "spoken_hook": hook_detail.get("spoken_hook"),
                "onscreen_hook": hook_detail.get("onscreen_hook"),
                "caption_hook": hook_detail.get("caption_hook"),
                "ocr_scope": "opening_frames",
                "ocr_note": (
                    "On-screen text is sampled at hook timestamps only, so pacing and "
                    "mid-video captioning are not in evidence. The text is often a "
                    "FRAGMENT ('THIS IS WHY', 'KILLS YOUR') because captions animate "
                    "word by word and a frame catches mid-phrase. Treat it as a clue "
                    "to the on-screen style, never as the full on-screen hook; the "
                    "spoken transcript and caption are the complete channels."
                ),
                "ocr_frames": (meta.get("ocr_evidence") or {}).get("frames") or [],
                "ocr_results": (meta.get("ocr_evidence") or {}).get("results") or [],
                "ocr_model": (meta.get("ocr_evidence") or {}).get("model"),
                "metrics": row.get("metrics") or {},
                "local_views_ratio": rolling.get(vid, {}).get("views_ratio"),
                "local_tier": rolling.get(vid, {}).get("tier"),
                "local_median_views": rolling.get(vid, {}).get("local_median_views"),
                "window_n": rolling.get(vid, {}).get("window_n"),
                "days_since_previous_post": cadence.get(vid, {}).get("days_since_previous_post"),
                "posts_in_same_week": cadence.get(vid, {}).get("posts_in_same_week"),
            }
            if include_transcript:
                packet["transcript"] = row.get("transcript")
                packet["transcript_segments"] = meta.get("transcript_segments") or []
                packet["transcript_status"] = meta.get("transcript_status")
            if include_components and components:
                packet["derived_annotation"] = {
                    "source": "pipeline LLM extraction, not ground truth",
                    "schema_version": (components.get("extraction") or {}).get("schema_version"),
                    "model": (components.get("extraction") or {}).get("model"),
                    "components": components,
                    "guidance": (
                        "These labels were assigned by a cheaper model from the transcript. "
                        "Read the caption and transcript above and disagree where warranted."
                    ),
                }
            packets.append(packet)

        result = {
            "account": handle,
            "account_scope_enforced": account_scope_enforced(),
            "corpus_truncated": _corpus_truncated(rows),
            "requested": len(video_ids),
            "returned": len(packets),
            "not_found": missing,
            "batch_limit": MAX_BATCH,
            "posts": packets,
        }
        log_tool_call(
            tool_name="get_peer_content_batch",
            request_summary=summary,
            success=True,
            entity_type="peer_library",
            entity_id=handle,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_peer_content_batch",
            request_summary=summary,
            success=False,
            entity_type="peer_library",
            entity_id=str(account),
            error=str(exc),
        )
        raise


def get_peer_comments(account: str, video_ids: list[str]) -> dict[str, Any]:
    """Audience-response signals for named posts. Optional drill-down only.

    Never part of the default analysis pass. What is synced is the labelled
    summary per video (themes, questions, objections), not the raw comment feed.
    """
    handle = _require_peer(account)
    summary = f"account={handle} n={len(video_ids or [])}"
    try:
        if not video_ids:
            raise PeerAccountError("video_ids is required: comments are a targeted drill-down.")
        if len(video_ids) > MAX_BATCH:
            raise PeerAccountError(f"Batch limit is {MAX_BATCH} videos.")

        rows = _all_rows(handle)
        by_id = {str(r.get("platform_post_id")): r for r in rows}

        items: list[dict[str, Any]] = []
        for vid in [str(v) for v in video_ids]:
            row = by_id.get(vid)
            if not row:
                items.append({"video_id": vid, "found": False})
                continue
            analysis = (row.get("metadata") or {}).get("comment_analysis") or {}
            items.append(
                {
                    "video_id": vid,
                    "found": True,
                    "comment_count_public": _num_or_none((row.get("metrics") or {}).get("comments")),
                    "comment_analysis": analysis,
                    "available": bool(analysis),
                }
            )

        result = {
            "account": handle,
            "account_scope_enforced": account_scope_enforced(),
            "posts": items,
            "note": (
                "Labelled summaries only; raw comment text is not synced to this store. "
                "Absent analysis means comments were never fetched for that video, which "
                "is the default for a peer library."
            ),
        }
        log_tool_call(
            tool_name="get_peer_comments",
            request_summary=summary,
            success=True,
            entity_type="peer_library",
            entity_id=handle,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_peer_comments",
            request_summary=summary,
            success=False,
            entity_type="peer_library",
            entity_id=str(account),
            error=str(exc),
        )
        raise


def get_peer_library_brief(account: str) -> dict[str, Any]:
    """Descriptive map of a peer library. Contains no conclusions by design.

    It answers "what is here and what can be measured", never "what works and
    why". Those are the analysis product, written after reading the content.
    """
    handle = _require_peer(account)
    summary = f"account={handle}"
    try:
        rows = _all_rows(handle)
        if not rows:
            return {
                "account": handle,
                "catalog_size": 0,
                "note": f"No synced posts for account '{handle}'. Run the peer ingest first.",
            }

        rolling = rolling_local_stats(rows)
        eras = [{k: v for k, v in e.items() if not k.startswith("_")} for e in detect_eras(rows)]
        dates = [str(r.get("posted_at") or "")[:10] for r in rows if r.get("posted_at")]
        tiers: dict[str, int] = {}
        for stats in rolling.values():
            tiers[stats["tier"]] = tiers.get(stats["tier"], 0) + 1

        ranked = sorted(
            (
                (video_id, stats)
                for video_id, stats in rolling.items()
                if stats.get("views_ratio") is not None
            ),
            key=lambda item: item[1]["views_ratio"],
            reverse=True,
        )
        top = [
            {"video_id": vid, "local_views_ratio": s.get("views_ratio"), "era": None}
            for vid, s in ranked[:10]
        ]
        bottom = [
            {"video_id": vid, "local_views_ratio": s.get("views_ratio")}
            for vid, s in ranked[-10:]
        ]
        era_map = _era_of(rows)
        for item in top:
            item["era"] = era_map.get(item["video_id"])

        with_transcript = sum(1 for r in rows if r.get("transcript"))
        with_components = sum(
            1 for r in rows if isinstance((r.get("metadata") or {}).get("components"), dict)
        )
        with_comments = sum(
            1 for r in rows if (r.get("metadata") or {}).get("comment_analysis")
        )
        deep_sample_count = sum(
            1
            for row in rows
            if (((row.get("metadata") or {}).get("sample_plan") or {}).get("is_deep_sample"))
        )
        transcript_chars = sum(len(str(row.get("transcript") or "")) for row in rows)
        segment_chars = sum(
            len(str(segment.get("text") or ""))
            for row in rows
            for segment in ((row.get("metadata") or {}).get("transcript_segments") or [])
            if isinstance(segment, dict)
        )
        isolation = _isolation_audit(handle, rows)

        result = {
            "account": handle,
            "account_scope_enforced": account_scope_enforced(),
            "isolation_audit": isolation,
            "corpus_truncated": _corpus_truncated(rows),
            "corpus_truncation_warning": _truncation_warning(rows),
            "catalog_size": len(rows),
            "date_range": {"first": min(dates) if dates else None, "last": max(dates) if dates else None},
            "eras": eras,
            "local_tier_counts": tiers,
            "top_by_local_ratio": top,
            "bottom_by_local_ratio": bottom,
            "coverage": {
                "transcripts": with_transcript,
                "components": with_components,
                "comment_analysis": with_comments,
                "deep_sample": deep_sample_count,
                "deep_sample_share": (
                    round(deep_sample_count / len(rows), 3) if rows else None
                ),
            },
            "context_budget": {
                "transcript_characters": transcript_chars,
                "timed_segment_characters": segment_chars,
                "estimated_transcript_tokens": round(transcript_chars / 4),
                "estimated_with_timed_segments_tokens": round(
                    (transcript_chars + segment_chars) / 4
                ),
                "guidance": (
                    "Load the lean manifest first. Read full transcripts in 10-25 post "
                    "batches selected across months, statistical eras and local tiers; "
                    "request timed/OCR detail only when sequence evidence is needed."
                ),
            },
            "not_measurable": NOT_MEASURABLE,
            "ritual": [
                "1. get_peer_era_summary — see the shape of the timeline.",
                "2. get_peer_corpus_manifest — lean rows; pick posts per era and tier.",
                "3. get_peer_content_batch — read captions and transcripts, 10-25 at a time.",
                "4. Write the four-section artefact: engine, why it works, portable vs "
                "him-specific, assignment template.",
                "Comments are optional and only for a named hypothesis. Do not load the "
                "DocMap strategy brief during peer analysis.",
            ],
            "note": (
                "This brief is a map, not a thesis. It deliberately contains no claim about "
                "what works or why; produce those by reading the posts."
            ),
        }
        log_tool_call(
            tool_name="get_peer_library_brief",
            request_summary=summary,
            success=True,
            entity_type="peer_library",
            entity_id=handle,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_peer_library_brief",
            request_summary=summary,
            success=False,
            entity_type="peer_library",
            entity_id=str(account),
            error=str(exc),
        )
        raise


GUIDELINES_SCHEMA = "content_guidelines_v1"
REQUIRED_GUIDELINE_SECTIONS = [str(i) for i in range(13)]
LIBRARY_INDEX_KEYS = {
    "handle",
    "specialty_key",
    "catalog_size",
    "sample_n",
    "coverage",
    "brief_status",
    "deep_status",
    "good_fit",
}


def _past_profiled(stage: str | None) -> bool:
    return (stage or "") in {"screened", "hydrated", "classified", "scored"}


def _open_ingest_job(corpus: Any) -> dict[str, Any]:
    existing = [
        job
        for job in corpus.list("creator_deep_jobs")
        if job.get("kind") == "deep_ingest" and job.get("status") in {"queued", "running"}
    ]
    if existing:
        return existing[0]
    return corpus.insert(
        "creator_deep_jobs",
        {"kind": "deep_ingest", "status": "running", "params": {}, "meta": {"standing": True}},
    )


def _queue_position(corpus: Any, item: dict[str, Any]) -> int:
    queued = [
        row
        for row in corpus.list("creator_deep_job_items")
        if row.get("status") in {"queued", "running"} and row.get("kind") == "deep_ingest"
    ]
    ordered = sorted(
        queued,
        key=lambda row: (-int(row.get("priority") or 0), str(row.get("created_at") or "")),
    )
    for index, row in enumerate(ordered, start=1):
        if row.get("id") == item.get("id"):
            return index
    return len(ordered) + 1


def _validate_guidelines(artefact: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if artefact.get("schema_version") != GUIDELINES_SCHEMA:
        errors.append("schema_version")
    sections = artefact.get("sections") or {}
    for key in REQUIRED_GUIDELINE_SECTIONS:
        if key not in sections:
            errors.append(f"missing_section_{key}")
    return errors


def request_deep_dive(
    handle: str,
    *,
    quality: str = "on_demand",
    confirmed: bool = False,
) -> dict[str, Any]:
    """Jump the L3 queue. Preview unless confirmed=true."""
    peer = _require_peer(handle)
    if quality not in {"auto", "on_demand"}:
        raise PeerAccountError("quality must be auto or on_demand")
    corpus = get_corpus()
    profile = corpus.get("creator_profiles", handle=peer)
    if not profile:
        raise PeerAccountError(f"no creator_profiles row for {peer}")
    stage = profile.get("stage")
    if stage == "unavailable" or not _past_profiled(stage):
        raise PeerAccountError(
            "handle must be past profiled (screened/hydrated/classified/scored) and not unavailable"
        )
    brief = corpus.get("creator_peer_briefs", account_handle=peer)
    ingest = corpus.get("creator_deep_job_items", item_key=profile["id"], kind="deep_ingest")
    preview = {
        "handle": peer,
        "preview": not confirmed,
        "quality": quality,
        "priority": 100,
        "stage": stage,
        "existing_brief": (brief or {}).get("status"),
        "ingest_status": (ingest or {}).get("status") or "none",
        "job_id": (ingest or {}).get("id"),
    }
    if not confirmed:
        return preview

    job = _open_ingest_job(corpus)
    item = corpus.upsert(
        "creator_deep_job_items",
        {
            "job_id": job["id"],
            "kind": "deep_ingest",
            "item_key": profile["id"],
            "priority": 100,
            "payload": {"handle": peer, "quality": quality},
            "status": (ingest or {}).get("status") or "queued",
        },
        keys=("kind", "item_key"),
    )
    corpus.update(
        "creator_deep_job_items",
        {
            "priority": 100,
            "payload": {"handle": peer, "quality": quality},
            "status": item.get("status") or "queued",
        },
        id=item["id"],
    )
    item = corpus.get("creator_deep_job_items", id=item["id"]) or item
    corpus.update(
        "creator_profiles",
        {
            "deep_status": "queued" if item.get("status") == "queued" else profile.get("deep_status"),
            "deep_quality": quality,
            "deep_job_id": item.get("id"),
        },
        id=profile["id"],
    )
    position = _queue_position(corpus, item)
    return {
        "handle": peer,
        "preview": False,
        "job_id": item.get("id"),
        "queue_position": position,
        "eta_hours": position * 4,
        "existing_brief": (brief or {}).get("status"),
        "ingest_status": item.get("status"),
        "priority": 100,
        "quality": quality,
    }


def get_deep_job(*, handle: str | None = None, job_id: str | None = None) -> dict[str, Any]:
    if not handle and not job_id:
        raise PeerAccountError("handle or job_id is required")
    corpus = get_corpus()
    item = None
    profile = None
    if job_id:
        item = corpus.get("creator_deep_job_items", id=job_id)
        if item:
            profile = corpus.get("creator_profiles", id=item.get("item_key"))
    if handle:
        peer = _require_peer(handle)
        profile = corpus.get("creator_profiles", handle=peer)
        if profile:
            item = corpus.get(
                "creator_deep_job_items",
                item_key=profile["id"],
                kind="deep_ingest",
            )
    if not profile:
        return {"found": False, "handle": handle, "job_id": job_id}
    brief = corpus.get("creator_peer_briefs", account_handle=profile.get("handle"))
    coverage = (brief or {}).get("coverage") or (item or {}).get("result") or {}
    position = _queue_position(corpus, item) if item else None
    return {
        "found": True,
        "handle": profile.get("handle"),
        "job_id": (item or {}).get("id"),
        "ingest_status": (item or {}).get("status") or "none",
        "deep_status": profile.get("deep_status"),
        "brief_status": (brief or {}).get("status"),
        "coverage": coverage,
        "queue_position": position,
        "eta_hours": (position * 4) if position else None,
        "priority": (item or {}).get("priority"),
    }


def list_peer_libraries(
    *,
    specialty_key: str | None = None,
    deep_status: str | None = None,
    cursor: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    page_size = min(max(int(limit or 50), 1), 50)
    corpus = get_corpus()
    profiles = corpus.list("creator_profiles")
    rows: list[dict[str, Any]] = []
    for profile in profiles:
        if specialty_key and profile.get("specialty_key") != specialty_key:
            continue
        if deep_status and profile.get("deep_status") != deep_status:
            continue
        if profile.get("deep_status") in {None, "none"} and not deep_status:
            continue
        handle = profile.get("handle")
        brief = corpus.get("creator_peer_briefs", account_handle=handle)
        coverage = (brief or {}).get("coverage") or {}
        rows.append(
            {
                "handle": handle,
                "specialty_key": profile.get("specialty_key"),
                "catalog_size": coverage.get("catalog_n") or profile.get("video_count"),
                "sample_n": coverage.get("sample_n"),
                "coverage": {
                    "transcript_yield": coverage.get("transcript_yield"),
                    "component_yield": coverage.get("component_yield"),
                    "timed_transcript_n": coverage.get("timed_transcript_n"),
                },
                "brief_status": (brief or {}).get("status"),
                "deep_status": profile.get("deep_status"),
                "good_fit": profile.get("good_fit"),
            }
        )
    total = len(rows)
    page = rows[cursor : cursor + page_size]
    dumped = json.dumps(page)
    if '"posts"' in dumped:
        raise PeerAccountError("list_peer_libraries refused a post payload")
    for row in page:
        extra = set(row) - LIBRARY_INDEX_KEYS
        if extra:
            raise PeerAccountError(f"unexpected library index fields: {sorted(extra)}")
    return {
        "total_rows": total,
        "returned_rows": len(page),
        "next_cursor": cursor + len(page) if cursor + len(page) < total else None,
        "libraries": page,
    }


def get_peer_transfer_brief(account: str) -> dict[str, Any]:
    handle = _require_peer(account)
    corpus = get_corpus()
    profile = corpus.get("creator_profiles", handle=handle)
    brief = corpus.get("creator_peer_briefs", account_handle=handle)
    ingest = None
    if profile:
        ingest = corpus.get("creator_deep_job_items", item_key=profile["id"], kind="deep_ingest")
    if not brief:
        return {
            "found": False,
            "account": handle,
            "ingest_status": (ingest or {}).get("status") or "none",
            "ritual": (
                "If ingest succeeded, use get_peer_library_brief for this one account. "
                "If queued, wait; do not treat L2 caption_hooks as spoken packets."
            ),
        }
    artefact = brief.get("artefact") or {}
    return {
        "found": True,
        "account": handle,
        "status": brief.get("status"),
        "source": brief.get("source"),
        "schema_version": brief.get("schema_version") or artefact.get("schema_version"),
        "artefact": artefact,
        "coverage": brief.get("coverage"),
        "unreviewed": brief.get("status") == "draft",
    }


def save_peer_transfer_brief(
    account: str,
    artefact: dict[str, Any],
    *,
    confirmed: bool = False,
) -> dict[str, Any]:
    handle = _require_peer(account)
    errors = _validate_guidelines(artefact)
    if errors:
        raise PeerAccountError(f"invalid content_guidelines_v1: {','.join(errors)}")
    preview = {
        "account": handle,
        "preview": not confirmed,
        "schema_version": artefact.get("schema_version"),
    }
    if not confirmed:
        return preview
    corpus = get_corpus()
    profile = corpus.get("creator_profiles", handle=handle)
    if not profile:
        raise PeerAccountError(f"no creator_profiles row for {handle}")
    row = corpus.upsert(
        "creator_peer_briefs",
        {
            "creator_profile_id": profile["id"],
            "account_handle": handle,
            "status": "confirmed",
            "source": "mcp_session",
            "schema_version": GUIDELINES_SCHEMA,
            "artefact": artefact,
            "coverage": artefact.get("coverage") or {},
        },
        keys=("account_handle",),
    )
    corpus.update("creator_profiles", {"deep_status": "brief_confirmed"}, id=profile["id"])
    return {"account": handle, "written": True, "brief_id": row.get("id"), "status": "confirmed"}
