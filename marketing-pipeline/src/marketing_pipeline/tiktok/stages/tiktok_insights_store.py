"""Persist TikTok insights and strategy state (file + Supabase sync)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from marketing_pipeline import config

InsightStatus = Literal["draft", "approved", "promoted"]

STATE_PATH = config.ANALYSIS_DIR / "tiktok_strategy_state.json"
STRATEGY_PLATFORM = "tiktok_meta"
STRATEGY_POST_ID = "strategy_state"


def _default_state() -> dict[str, Any]:
    return {
        "insights": [],
        "approved_patterns": [],
        "changelog": [],
        "updated_at": None,
    }


def load_state(path: Path | None = None) -> dict[str, Any]:
    target = path or STATE_PATH
    if not target.exists():
        return _default_state()
    data = json.loads(target.read_text(encoding="utf-8"))
    data.setdefault("insights", [])
    data.setdefault("approved_patterns", [])
    data.setdefault("changelog", [])
    return data


def save_state(state: dict[str, Any], path: Path | None = None) -> Path:
    target = path or STATE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    target.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def draft_insight(
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
    state = load_state()
    insight_id = str(uuid.uuid4())
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
    save_state(state)
    return entry


def approve_insight(
    insight_id: str,
    *,
    approved_by: str | None = None,
    learning: str | None = None,
) -> dict[str, Any] | None:
    state = load_state()
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
        save_state(state)
        return entry
    return None


def list_insights(*, status: InsightStatus | None = None) -> list[dict[str, Any]]:
    state = load_state()
    items = list(state.get("insights") or [])
    if status:
        items = [i for i in items if i.get("status") == status]
    return items
