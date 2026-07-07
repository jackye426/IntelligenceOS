"""TikTok insight draft/approve workflow for MCP."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from common.audit import log_tool_call
from tools.tiktok_strategy_state import fetch_strategy_row, save_strategy_metadata


def _state_from_row() -> dict[str, Any]:
    row = fetch_strategy_row()
    if not row:
        return {"insights": [], "changelog": [], "approved_patterns": []}
    meta = row.get("metadata") or {}
    return {
        "insights": list(meta.get("insights") or []),
        "changelog": list(meta.get("changelog") or []),
        "approved_patterns": list(meta.get("approved_patterns") or []),
        "strategy_brief": meta.get("strategy_brief") or {},
    }


def _persist_state(state: dict[str, Any]) -> None:
    row = fetch_strategy_row()
    meta = (row.get("metadata") if row else {}) or {}
    meta["insights"] = state["insights"]
    meta["changelog"] = state["changelog"]
    meta["approved_patterns"] = state.get("approved_patterns") or []
    if state.get("strategy_brief"):
        meta["strategy_brief"] = state["strategy_brief"]
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_strategy_metadata(meta)


def draft_tiktok_insight(
    *,
    group_id: str,
    video_ids: list[str],
    what_we_tried: str,
    expectation: str | None = None,
    outcome: str | None = None,
    learning: str | None = None,
    cluster_basis: str = "manual",
    confidence: str = "medium",
    playbook_themes: list[str] | None = None,
) -> dict[str, Any]:
    summary = f"group_id={group_id} videos={len(video_ids)}"
    try:
        state = _state_from_row()
        insight_id = str(uuid4())
        entry = {
            "insight_id": insight_id,
            "group_id": group_id,
            "video_ids": video_ids,
            "cluster_basis": cluster_basis,
            "confidence": confidence,
            "what_we_tried": what_we_tried,
            "expectation": expectation,
            "outcome": outcome,
            "learning": learning,
            "playbook_themes": playbook_themes or [],
            "status": "draft",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "approved_at": None,
            "approved_by": None,
        }
        state["insights"].append(entry)
        _persist_state(state)
        result = {"ok": True, "insight": entry, "next_step": "User reviews; call approve_tiktok_insight when agreed."}
        log_tool_call(tool_name="draft_tiktok_insight", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(tool_name="draft_tiktok_insight", request_summary=summary, success=False, error=str(exc))
        raise


def approve_tiktok_insight(
    insight_id: str,
    *,
    approved_by: str | None = None,
    learning: str | None = None,
) -> dict[str, Any]:
    summary = f"insight_id={insight_id}"
    try:
        state = _state_from_row()
        for entry in state["insights"]:
            if entry.get("insight_id") != insight_id:
                continue
            if learning:
                entry["learning"] = learning
            entry["status"] = "approved"
            entry["approved_at"] = datetime.now(timezone.utc).isoformat()
            entry["approved_by"] = approved_by
            line = (
                f"{entry['approved_at'][:10]}: [{entry.get('group_id')}] "
                f"{entry.get('learning') or entry.get('what_we_tried', '')}"
            )
            state["changelog"].append(line)
            brief = state.get("strategy_brief") or {}
            approved = [i for i in state["insights"] if i.get("status") == "approved"]
            brief["3_approved_insights"] = approved
            brief["4_open_drafts"] = [i for i in state["insights"] if i.get("status") == "draft"]
            brief["6_changelog"] = state["changelog"]
            state["strategy_brief"] = brief
            _persist_state(state)
            result = {
                "ok": True,
                "insight": entry,
                "note": "Saved to approved learnings. Constitution unchanged — use propose_constitution_patch to promote.",
            }
            log_tool_call(tool_name="approve_tiktok_insight", request_summary=summary, success=True)
            return result
        return {"ok": False, "error": f"insight_id {insight_id} not found"}
    except Exception as exc:  # noqa: BLE001
        log_tool_call(tool_name="approve_tiktok_insight", request_summary=summary, success=False, error=str(exc))
        raise


def list_tiktok_insight_drafts(*, limit: int = 20) -> dict[str, Any]:
    state = _state_from_row()
    drafts = [i for i in state["insights"] if i.get("status") == "draft"]
    return {"drafts": drafts[:limit], "count": len(drafts)}


def propose_constitution_patch(
    *,
    insight_id: str,
    proposed_bullet: str,
    target_section: str = "content-instruction.md",
) -> dict[str, Any]:
    """Gate 2: returns markdown for human to paste — never auto-writes constitution."""
    state = _state_from_row()
    insight = next((i for i in state["insights"] if i.get("insight_id") == insight_id), None)
    if not insight:
        return {"ok": False, "error": f"insight_id {insight_id} not found"}
    if insight.get("status") != "approved":
        return {"ok": False, "error": "Insight must be approved (Gate 1) before constitution promotion."}
    patch = (
        f"## Proposed addition to {target_section}\n\n"
        f"- {proposed_bullet}\n\n"
        f"Source insight: {insight.get('group_id')} ({insight_id})\n"
        f"Learning: {insight.get('learning')}\n\n"
        "**This is NOT applied automatically.** Paste into "
        f"`marketing-pipeline/tiktok/data/playbooks/{target_section}` then run sync-playbooks."
    )
    return {"ok": True, "patch_markdown": patch, "insight_id": insight_id}
