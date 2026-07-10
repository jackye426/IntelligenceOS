"""MCP read/slice tools for batch-extracted video components."""

from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any, Literal

from common.audit import log_tool_call
from tools.tiktok_metrics_layers import compute_velocity, fetch_latest_studio_insight, fetch_metric_snapshots
from tools.tiktok_shared import fetch_tiktok_post, fetch_tiktok_posts, filter_by_date, saves_per_1k

GroupBy = Literal[
    "hook.type",
    "funnel_stage",
    "cta.present",
    "format_raw",
    "speaker.type_raw",
    "hook.channel",
]
MetricName = Literal[
    "views",
    "saves_per_1k",
    "shares",
    "engagement",
    "comments",
]


FUNNEL_PRIMARY_METRICS = {
    "TOFU": ["views", "shares"],
    "MOFU": ["saves_per_1k", "comments"],
    "BOFU": ["saves_per_1k"],  # bookings/clicks not available yet
}


def _components_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    meta = row.get("metadata") or {}
    comp = meta.get("components")
    return comp if isinstance(comp, dict) else None


def _nested_get(comp: dict[str, Any], dotted: str) -> Any:
    cur: Any = comp
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _engagement(metrics: dict[str, Any]) -> int:
    return int(metrics.get("likes") or 0) + int(metrics.get("comments") or 0) + int(
        metrics.get("shares") or 0
    )


def _metric_value(row: dict[str, Any], metric: MetricName) -> float | None:
    metrics = row.get("metrics") or {}
    if metric == "views":
        v = metrics.get("views")
        return float(v) if v is not None else None
    if metric == "saves_per_1k":
        return float(saves_per_1k(metrics))
    if metric == "shares":
        v = metrics.get("shares")
        return float(v) if v is not None else None
    if metric == "comments":
        v = metrics.get("comments")
        return float(v) if v is not None else None
    if metric == "engagement":
        return float(_engagement(metrics))
    return None


def get_video_components(video_id: str) -> dict[str, Any]:
    summary = f"video_id={video_id}"
    try:
        row = fetch_tiktok_post(video_id)
        if not row:
            result = {"ok": False, "found": False, "error": f"Video {video_id} not found"}
            log_tool_call(tool_name="get_video_components", request_summary=summary, success=False)
            return result
        comp = _components_from_row(row)
        studio = fetch_latest_studio_insight(video_id)
        snapshots = fetch_metric_snapshots(video_id, hours=72)
        velocity = compute_velocity(snapshots) if snapshots else None
        retention_available = bool(
            studio
            and (
                (studio.get("metrics") or {}).get("avg_watch_time") is not None
                or (studio.get("metrics") or {}).get("finish_rate") is not None
                or (studio.get("metrics") or {}).get("video_finish_rate_realtime") is not None
            )
        )
        result = {
            "ok": True,
            "found": True,
            "video_id": video_id,
            "posted_at": row.get("posted_at"),
            "posted_at_note": "Cite this UTC publish timestamp only. Do not infer date from video_id.",
            "post_url": row.get("post_url"),
            "metrics": row.get("metrics") or {},
            "components": comp,
            "components_available": comp is not None,
            "studio_insight": (
                {"captured_at": studio.get("captured_at"), "metrics": studio.get("metrics")}
                if studio
                else None
            ),
            "velocity": velocity,
            "retention_metrics_available": retention_available,
            "note": (
                None
                if comp
                else "No components yet — run: marketing_pipeline tiktok extract-components && sync-supabase"
            ),
        }
        log_tool_call(tool_name="get_video_components", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_video_components",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise


def list_videos_by_component(
    *,
    field: str = "hook.type",
    value_contains: str | None = None,
    exact_value: str | None = None,
    funnel_stage: str | None = None,
    cta_present: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    summary = f"field={field} value={exact_value or value_contains}"
    try:
        rows = filter_by_date(fetch_tiktok_posts(limit=500), since=since)
        matched: list[dict[str, Any]] = []
        for row in rows:
            comp = _components_from_row(row)
            if not comp:
                continue
            if funnel_stage and str(comp.get("funnel_stage")) != funnel_stage:
                continue
            if cta_present is not None:
                present = comp.get("cta", {}).get("present") if isinstance(comp.get("cta"), dict) else None
                want = cta_present.lower()
                if want in {"true", "false"}:
                    if str(present).lower() != want:
                        continue
                elif want == "unclear" and present != "unclear":
                    continue
            val = _nested_get(comp, field)
            if exact_value is not None and str(val) != exact_value:
                continue
            if value_contains is not None and value_contains.lower() not in str(val or "").lower():
                continue
            metrics = row.get("metrics") or {}
            matched.append(
                {
                    "video_id": row.get("platform_post_id"),
                    "posted_at": row.get("posted_at"),
                    "post_url": row.get("post_url"),
                    "hook": row.get("hook"),
                    "field_value": val,
                    "funnel_stage": comp.get("funnel_stage"),
                    "cta_present": (comp.get("cta") or {}).get("present"),
                    "views": metrics.get("views"),
                    "saves_per_1k_views": saves_per_1k(metrics),
                    "shares": metrics.get("shares"),
                }
            )
            if len(matched) >= limit:
                break
        result = {
            "ok": True,
            "count": len(matched),
            "filters": {
                "field": field,
                "value_contains": value_contains,
                "exact_value": exact_value,
                "funnel_stage": funnel_stage,
                "cta_present": cta_present,
                "since": since,
            },
            "videos": matched,
        }
        log_tool_call(tool_name="list_videos_by_component", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="list_videos_by_component",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise


def analyze_components(
    *,
    group_by: GroupBy = "hook.type",
    metric: MetricName | None = None,
    since: str | None = None,
    funnel_stage: str | None = None,
    min_n: int = 1,
) -> dict[str, Any]:
    summary = f"group_by={group_by} metric={metric}"
    try:
        rows = filter_by_date(fetch_tiktok_posts(limit=500), since=since)
        buckets: dict[str, list[float]] = defaultdict(list)
        funnel_counts: dict[str, int] = defaultdict(int)
        with_components = 0
        for row in rows:
            comp = _components_from_row(row)
            if not comp:
                continue
            with_components += 1
            stage = str(comp.get("funnel_stage") or "unclear")
            if funnel_stage and stage != funnel_stage:
                continue
            funnel_counts[stage] += 1
            key = _nested_get(comp, group_by)
            key_s = str(key) if key is not None else "null"
            # Choose metric
            use_metric: MetricName
            if metric:
                use_metric = metric
            elif funnel_stage == "TOFU":
                use_metric = "views"
            elif funnel_stage == "MOFU":
                use_metric = "saves_per_1k"
            elif funnel_stage == "BOFU":
                use_metric = "saves_per_1k"
            else:
                use_metric = "views"
            val = _metric_value(row, use_metric)
            if val is None:
                continue
            buckets[key_s].append(val)

        resolved_metric = metric or (
            "views"
            if not funnel_stage or funnel_stage == "TOFU"
            else "saves_per_1k"
        )
        groups = []
        for key, vals in sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            if len(vals) < min_n:
                continue
            groups.append(
                {
                    "key": key,
                    "n": len(vals),
                    "metric": resolved_metric,
                    "median": round(median(vals), 2),
                    "min": round(min(vals), 2),
                    "max": round(max(vals), 2),
                }
            )

        warnings: list[str] = []
        if not metric and not funnel_stage and any(s == "BOFU" for s in funnel_counts):
            warnings.append(
                "Mixed funnel stages ranked with views by default — do not treat BOFU as weak solely on views. "
                "Pass funnel_stage=BOFU and/or metric=saves_per_1k; bookings/link clicks not available yet."
            )
        if funnel_stage == "BOFU":
            warnings.append(
                "BOFU primary commercial metrics (link clicks, enquiries, bookings) are not wired — "
                "using proxy metrics only; CTA success claims are not supported yet."
            )
        warnings.append(
            "Retention metrics (3s hold, AWT, finish rate) are not in this aggregation — "
            "use get_video_components for studio/velocity when available; conclusions weaker without them."
        )

        result = {
            "ok": True,
            "group_by": group_by,
            "metric": resolved_metric,
            "videos_with_components": with_components,
            "funnel_counts": dict(funnel_counts),
            "groups": groups,
            "funnel_primary_metrics_guide": FUNNEL_PRIMARY_METRICS,
            "warnings": warnings,
        }
        log_tool_call(tool_name="analyze_components", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="analyze_components",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise
