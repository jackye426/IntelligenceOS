"""Record human-approved A/B hook learnings on involved TikTok videos."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from common.audit import log_tool_call
from common.supabase_client import get_client
from tools.tiktok_shared import fetch_tiktok_posts

Confidence = Literal["high", "medium", "low"]


def _videos_for_pair(rows: list[dict[str, Any]], pair_id: str) -> set[str]:
    ids: set[str] = set()
    for row in rows:
        vid = str(row.get("platform_post_id") or "")
        meta = row.get("metadata") or {}
        for ref in meta.get("ab_pairs") or []:
            if ref.get("pair_id") == pair_id:
                ids.add(vid)
                partner = str(ref.get("partner_video_id") or "")
                if partner:
                    ids.add(partner)
    return ids


def record_ab_learning(
    pair_id: str,
    learning: str,
    winner_video_id: str,
    *,
    hook_pattern: str | None = None,
    confidence: Confidence = "medium",
    loser_video_id: str | None = None,
    reposted_as: str | None = None,
    reviewed_by: str | None = None,
) -> dict[str, Any]:
    summary = f"pair_id={pair_id} winner={winner_video_id}"
    try:
        client = get_client()
        rows = fetch_tiktok_posts()
        video_ids = _videos_for_pair(rows, pair_id)

        if not video_ids:
            return {
                "ok": False,
                "error": f"No videos found with pair_id={pair_id!r}",
                "pair_id": pair_id,
            }

        if winner_video_id not in video_ids:
            return {
                "ok": False,
                "error": f"winner_video_id {winner_video_id} not in pair {pair_id}",
                "pair_id": pair_id,
                "video_ids": sorted(video_ids),
            }

        payload = {
            "pair_id": pair_id,
            "learning": learning.strip(),
            "winner_video_id": winner_video_id,
            "loser_video_id": loser_video_id,
            "hook_pattern": hook_pattern,
            "confidence": confidence,
            "learning_status": "approved",
            "reviewed_by": reviewed_by,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "reposted_as": reposted_as,
        }

        updated: list[str] = []
        for vid in video_ids:
            row = next((r for r in rows if str(r.get("platform_post_id")) == vid), None)
            if not row:
                continue
            meta = dict(row.get("metadata") or {})
            meta["ab_learning"] = payload
            # Enrich ab_pairs entries with learning text
            pairs = []
            for ref in meta.get("ab_pairs") or []:
                ref = dict(ref)
                if ref.get("pair_id") == pair_id:
                    ref["learning"] = learning.strip()
                pairs.append(ref)
            meta["ab_pairs"] = pairs
            client.table("content_posts").update({"metadata": meta}).eq("id", row["id"]).execute()
            updated.append(vid)

        result = {
            "ok": True,
            "pair_id": pair_id,
            "updated_video_ids": updated,
            "learning": payload,
        }
        log_tool_call(
            tool_name="record_ab_learning",
            request_summary=summary,
            success=True,
            entity_type="tiktok_ab_pair",
            entity_id=pair_id,
            action_type="write",
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="record_ab_learning",
            request_summary=summary,
            success=False,
            entity_type="tiktok_ab_pair",
            entity_id=pair_id,
            action_type="write",
            error=str(exc),
        )
        raise
