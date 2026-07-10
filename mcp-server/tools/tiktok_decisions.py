"""TikTok decision log — forward commitments + outcome checks for MCP."""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import Any, Literal
from uuid import uuid4

from common.audit import log_tool_call
from tools.tiktok_strategy_state import fetch_strategy_row, save_strategy_metadata

ActionType = Literal[
    "repost_hook",
    "new_film",
    "kill_angle",
    "hold",
    "test_variant",
    "other",
]
DecisionStatus = Literal["proposed", "committed", "done", "outcome_recorded", "cancelled"]
Verdict = Literal["confirmed", "mixed", "failed", "inconclusive"]
Implication = Literal["keep", "avoid", "promote_candidate", "needs_another_test"]

OPEN_STATUSES = frozenset({"proposed", "committed", "done"})
DEFAULT_REVIEW_DAYS = 7


def _state_from_row() -> dict[str, Any]:
    row = fetch_strategy_row()
    if not row:
        return {"decisions": [], "strategy_brief": {}, "insights": [], "changelog": [], "approved_patterns": []}
    meta = row.get("metadata") or {}
    return {
        "decisions": list(meta.get("decisions") or []),
        "strategy_brief": meta.get("strategy_brief") or {},
        "insights": list(meta.get("insights") or []),
        "changelog": list(meta.get("changelog") or []),
        "approved_patterns": list(meta.get("approved_patterns") or []),
    }


def _persist_state(state: dict[str, Any]) -> None:
    row = fetch_strategy_row()
    meta = (row.get("metadata") if row else {}) or {}
    meta["decisions"] = state["decisions"]
    meta["insights"] = state.get("insights") or meta.get("insights") or []
    meta["changelog"] = state.get("changelog") or meta.get("changelog") or []
    meta["approved_patterns"] = state.get("approved_patterns") or meta.get("approved_patterns") or []
    brief = state.get("strategy_brief") or meta.get("strategy_brief") or {}
    brief["7_decisions"] = compact_decisions_for_brief(state["decisions"])
    meta["strategy_brief"] = brief
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_strategy_metadata(meta)


def compact_decisions_for_brief(
    decisions: list[dict[str, Any]],
    *,
    open_limit: int = 15,
    closed_limit: int = 10,
) -> dict[str, Any]:
    """Compact open + recent closed decisions for strategy brief §7."""
    open_items = [d for d in decisions if d.get("status") in OPEN_STATUSES]
    closed = [
        d
        for d in decisions
        if d.get("status") in {"outcome_recorded", "cancelled"}
    ]
    closed.sort(key=lambda d: d.get("closed_at") or d.get("created_at") or "", reverse=True)

    def slim(d: dict[str, Any]) -> dict[str, Any]:
        out = {
            "decision_id": d.get("decision_id"),
            "platform": d.get("platform"),
            "status": d.get("status"),
            "decision": d.get("decision"),
            "action_type": d.get("action_type"),
            "success_criteria": d.get("success_criteria"),
            "review_after": d.get("review_after"),
            "related_video_ids": d.get("related_video_ids") or [],
            "group_id": d.get("group_id"),
        }
        if d.get("outcome"):
            out["outcome"] = d["outcome"]
        if d.get("implication"):
            out["implication"] = d["implication"]
        return out

    return {
        "open": [slim(d) for d in open_items[:open_limit]],
        "recent_closed": [slim(d) for d in closed[:closed_limit]],
        "open_count": len(open_items),
        "closed_count": len(closed),
    }


def decisions_excerpt_for_prompt(
    decisions: list[dict[str, Any]] | None = None,
    *,
    max_chars: int = 2000,
) -> str:
    items = decisions if decisions is not None else _state_from_row()["decisions"]
    compact = compact_decisions_for_brief(items)
    lines = ["## Open decisions"]
    if not compact["open"]:
        lines.append("(none)")
    for d in compact["open"]:
        due = d.get("review_after") or "?"
        lines.append(
            f"- [{d.get('decision_id')}] ({d.get('status')}, review_after={due}) "
            f"{d.get('decision')}"
        )
    lines.append("## Recent closed decisions")
    if not compact["recent_closed"]:
        lines.append("(none)")
    for d in compact["recent_closed"]:
        verdict = (d.get("outcome") or {}).get("verdict") if isinstance(d.get("outcome"), dict) else None
        lines.append(
            f"- [{d.get('decision_id')}] verdict={verdict or d.get('status')} "
            f"{d.get('decision')} → {d.get('implication') or ''}"
        )
    return "\n".join(lines)[:max_chars]


def _parse_review_after(value: str | None) -> str:
    if value:
        return value[:10]
    return (date.today() + timedelta(days=DEFAULT_REVIEW_DAYS)).isoformat()


def is_due(decision: dict[str, Any], *, today: date | None = None) -> bool:
    """True when open and review_after <= today."""
    if decision.get("status") not in OPEN_STATUSES:
        return False
    raw = decision.get("review_after")
    if not raw:
        return True
    try:
        due = date.fromisoformat(str(raw)[:10])
    except ValueError:
        return True
    return due <= (today or date.today())


def log_tiktok_decision(
    decision: str,
    *,
    rationale: str | None = None,
    related_video_ids: list[str] | None = None,
    related_insight_ids: list[str] | None = None,
    group_id: str | None = None,
    action_type: ActionType = "other",
    success_criteria: str | None = None,
    review_after: str | None = None,
    expected_signals: list[dict[str, Any]] | None = None,
    platform: str = "tiktok",
    status: DecisionStatus = "committed",
    created_by: str | None = None,
    source_session: str | None = None,
) -> dict[str, Any]:
    summary = f"action={action_type} status={status}"
    try:
        text = decision.strip()
        if not text:
            return {"ok": False, "error": "decision text is required"}
        if status not in {"proposed", "committed"}:
            return {"ok": False, "error": "log_tiktok_decision status must be proposed or committed"}

        state = _state_from_row()
        entry = {
            "decision_id": str(uuid4()),
            "platform": platform or "tiktok",
            "status": status,
            "decision": text,
            "rationale": (rationale or "").strip() or None,
            "related_video_ids": related_video_ids or [],
            "related_insight_ids": related_insight_ids or [],
            "group_id": group_id,
            "action_type": action_type,
            "success_criteria": (success_criteria or "").strip() or None,
            "review_after": _parse_review_after(review_after),
            "expected_signals": expected_signals or [],
            "outcome": None,
            "implication": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "closed_at": None,
            "created_by": created_by,
            "source_session": source_session,
            "cancel_reason": None,
        }
        state["decisions"].append(entry)
        _persist_state(state)
        result = {
            "ok": True,
            "decision": entry,
            "next_step": (
                "After the action ships and review_after passes, pull live metrics then "
                "call record_decision_outcome with a human-confirmed verdict."
            ),
        }
        log_tool_call(tool_name="log_tiktok_decision", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(tool_name="log_tiktok_decision", request_summary=summary, success=False, error=str(exc))
        raise


def list_open_decisions(
    *,
    due_only: bool = False,
    platform: str | None = "tiktok",
    limit: int = 50,
) -> dict[str, Any]:
    summary = f"due_only={due_only} platform={platform}"
    try:
        state = _state_from_row()
        items = [d for d in state["decisions"] if d.get("status") in OPEN_STATUSES]
        if platform:
            items = [d for d in items if (d.get("platform") or "tiktok") == platform]
        if due_only:
            items = [d for d in items if is_due(d)]
        items.sort(key=lambda d: d.get("review_after") or d.get("created_at") or "")
        result = {
            "ok": True,
            "decisions": items[:limit],
            "count": len(items),
            "due_count": sum(1 for d in items if is_due(d)),
            "filters": {"due_only": due_only, "platform": platform, "limit": limit},
        }
        log_tool_call(tool_name="list_open_decisions", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(tool_name="list_open_decisions", request_summary=summary, success=False, error=str(exc))
        raise


def get_tiktok_decision(decision_id: str) -> dict[str, Any]:
    summary = f"decision_id={decision_id}"
    try:
        state = _state_from_row()
        entry = next((d for d in state["decisions"] if d.get("decision_id") == decision_id), None)
        if not entry:
            result = {"ok": False, "found": False, "error": f"decision_id {decision_id} not found"}
        else:
            result = {"ok": True, "found": True, "decision": entry, "due": is_due(entry)}
        log_tool_call(tool_name="get_tiktok_decision", request_summary=summary, success=bool(entry))
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(tool_name="get_tiktok_decision", request_summary=summary, success=False, error=str(exc))
        raise


def record_decision_outcome(
    decision_id: str,
    *,
    verdict: Verdict,
    metrics_summary: str | None = None,
    implication: Implication | None = None,
    confirmed: bool = False,
    reviewed_by: str | None = None,
) -> dict[str, Any]:
    """Close a decision with a human-confirmed verdict. Never invent outcomes."""
    summary = f"decision_id={decision_id} verdict={verdict}"
    try:
        if not confirmed:
            return {
                "ok": False,
                "error": "Set confirmed=true after the human agrees the verdict. Do not auto-close.",
                "decision_id": decision_id,
            }
        state = _state_from_row()
        for entry in state["decisions"]:
            if entry.get("decision_id") != decision_id:
                continue
            if entry.get("status") == "cancelled":
                return {"ok": False, "error": "Decision was cancelled; cannot record outcome."}
            now = datetime.now(timezone.utc).isoformat()
            entry["status"] = "outcome_recorded"
            entry["closed_at"] = now
            entry["outcome"] = {
                "verdict": verdict,
                "metrics_summary": (metrics_summary or "").strip() or None,
                "reviewed_by": reviewed_by,
                "recorded_at": now,
            }
            if implication:
                entry["implication"] = implication
            _persist_state(state)
            result = {
                "ok": True,
                "decision": entry,
                "note": (
                    "Outcome recorded. Optionally draft_tiktok_insight linked via related_insight_ids; "
                    "constitution unchanged unless propose_constitution_patch."
                ),
            }
            log_tool_call(tool_name="record_decision_outcome", request_summary=summary, success=True)
            return result
        return {"ok": False, "error": f"decision_id {decision_id} not found"}
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="record_decision_outcome",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise


def cancel_tiktok_decision(
    decision_id: str,
    *,
    reason: str | None = None,
    cancelled_by: str | None = None,
) -> dict[str, Any]:
    summary = f"decision_id={decision_id}"
    try:
        state = _state_from_row()
        for entry in state["decisions"]:
            if entry.get("decision_id") != decision_id:
                continue
            if entry.get("status") == "outcome_recorded":
                return {"ok": False, "error": "Decision already has an outcome; cannot cancel."}
            now = datetime.now(timezone.utc).isoformat()
            entry["status"] = "cancelled"
            entry["closed_at"] = now
            entry["cancel_reason"] = (reason or "").strip() or None
            entry["cancelled_by"] = cancelled_by
            _persist_state(state)
            result = {"ok": True, "decision": entry}
            log_tool_call(tool_name="cancel_tiktok_decision", request_summary=summary, success=True)
            return result
        return {"ok": False, "error": f"decision_id {decision_id} not found"}
    except Exception as exc:  # noqa: BLE001
        log_tool_call(tool_name="cancel_tiktok_decision", request_summary=summary, success=False, error=str(exc))
        raise


def mark_decision_done(decision_id: str) -> dict[str, Any]:
    """Optional: mark action shipped while waiting for metrics (status=done)."""
    state = _state_from_row()
    for entry in state["decisions"]:
        if entry.get("decision_id") != decision_id:
            continue
        if entry.get("status") not in {"proposed", "committed"}:
            return {"ok": False, "error": f"Cannot mark done from status={entry.get('status')}"}
        entry["status"] = "done"
        _persist_state(state)
        return {"ok": True, "decision": entry}
    return {"ok": False, "error": f"decision_id {decision_id} not found"}
