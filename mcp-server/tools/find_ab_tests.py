"""Filter and return TikTok A/B hook tests from content_posts."""

from __future__ import annotations

from typing import Any, Literal

from common.audit import log_tool_call
from tools.tiktok_shared import WinnerBy, aggregate_ab_tests, fetch_tiktok_posts, rank_posts

HookSource = Literal["ocr", "spoken", "caption"]


def find_ab_tests(
    *,
    min_views: int = 0,
    hook_source: HookSource | None = None,
    since: str | None = None,
    limit: int = 50,
    winner_by: WinnerBy = "views",
    group_by_pair_id: bool = False,
) -> dict[str, Any]:
    summary = (
        f"min_views={min_views} hook_source={hook_source} since={since} "
        f"limit={limit} winner_by={winner_by}"
    )
    try:
        rows = fetch_tiktok_posts()
        posted_by_video = {str(r.get("platform_post_id")): r.get("posted_at") for r in rows}
        tests = aggregate_ab_tests(
            rows,
            winner_by=winner_by,
            dedupe_by_pair_id=group_by_pair_id,
        )

        if since:
            tests = [
                t
                for t in tests
                if (
                    str(posted_by_video.get(str(t.get("video_id")) or "") or "")[:10] >= since
                )
                or (
                    str(posted_by_video.get(str(t.get("partner_video_id")) or "") or "")[:10]
                    >= since
                )
            ]

        if min_views > 0:
            tests = [
                t
                for t in tests
                if int((t.get("video_metrics") or {}).get("views") or 0) >= min_views
                or int((t.get("partner_metrics") or {}).get("views") or 0) >= min_views
            ]

        if hook_source:
            tests = [
                t
                for t in tests
                if t.get("video_hook_source") == hook_source
                or t.get("partner_hook_source") == hook_source
            ]

        tests.sort(
            key=lambda t: max(
                int(t.get("video_views") or 0),
                int(t.get("partner_views") or 0),
            ),
            reverse=True,
        )

        # Group multi-arm pairs (e.g. MRI 3-video cluster) when requested
        grouped: list[dict[str, Any]] | None = None
        if group_by_pair_id:
            by_pair: dict[str, dict[str, Any]] = {}
            for t in tests:
                pid = str(t.get("pair_id") or "")
                if pid not in by_pair:
                    by_pair[pid] = {
                        "pair_id": pid,
                        "learning": t.get("learning"),
                        "edges": [],
                        "video_ids": set(),
                    }
                by_pair[pid]["edges"].append(t)
                by_pair[pid]["video_ids"].add(t.get("video_id"))
                by_pair[pid]["video_ids"].add(t.get("partner_video_id"))
            grouped = []
            for entry in by_pair.values():
                entry["video_ids"] = sorted(v for v in entry["video_ids"] if v)
                grouped.append(entry)

        result = {
            "ab_tests": tests[:limit],
            "count": len(tests),
            "filters": {
                "min_views": min_views,
                "hook_source": hook_source,
                "since": since,
                "limit": limit,
                "winner_by": winner_by,
                "group_by_pair_id": group_by_pair_id,
            },
        }
        if grouped is not None:
            result["ab_test_groups"] = grouped[:limit]

        log_tool_call(tool_name="find_ab_tests", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="find_ab_tests",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise
