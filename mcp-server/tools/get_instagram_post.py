"""Full Instagram post lookup."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from tools.instagram_shared import fetch_instagram_post, post_summary


def get_instagram_post(post_id: str) -> dict[str, Any]:
    summary = f"post_id={post_id}"
    try:
        row = fetch_instagram_post(post_id)
        if not row:
            result = {"found": False, "post_id": post_id}
        else:
            meta = row.get("metadata") or {}
            result = {
                "found": True,
                **post_summary(row),
                "caption": row.get("caption"),
                "transcript": row.get("transcript"),
                "components": meta.get("instagram_components") or {},
                "child_media": meta.get("child_media") or [],
                "source_layers": meta.get("raw_source_layers") or [],
                "content_tracker": meta.get("content_tracker"),
            }
        log_tool_call(tool_name="get_instagram_post", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_instagram_post",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise

