"""List approved A/B hook learnings from content_posts metadata."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from tools.tiktok_shared import fetch_tiktok_posts, filter_by_date


def get_ab_learnings(
    *,
    pair_id: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    summary = f"pair_id={pair_id} since={since} limit={limit}"
    try:
        rows = fetch_tiktok_posts()
        if since:
            rows = filter_by_date(rows, since=since)

        by_pair: dict[str, dict[str, Any]] = {}
        for row in rows:
            meta = row.get("metadata") or {}
            learning = meta.get("ab_learning")
            if not learning or learning.get("learning_status") != "approved":
                continue
            pid = str(learning.get("pair_id") or "")
            if pair_id and pid != pair_id:
                continue
            if pid not in by_pair:
                by_pair[pid] = {**learning, "video_ids": set()}
            by_pair[pid]["video_ids"].add(str(row.get("platform_post_id")))

        learnings = []
        for entry in by_pair.values():
            entry = dict(entry)
            entry["video_ids"] = sorted(entry.pop("video_ids"))
            learnings.append(entry)

        learnings.sort(key=lambda x: str(x.get("reviewed_at") or ""), reverse=True)

        result = {
            "learnings": learnings[:limit],
            "count": len(learnings),
        }
        log_tool_call(tool_name="get_ab_learnings", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_ab_learnings",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise
