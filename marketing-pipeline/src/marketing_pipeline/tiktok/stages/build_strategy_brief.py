"""Assemble TikTok strategy brief for Claude MCP."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from marketing_pipeline import config
from marketing_pipeline.tiktok.models import TikTokMarketingDataset
from marketing_pipeline.tiktok.stages.ab_pair_registry import load_registry_pairs
from marketing_pipeline.tiktok.stages.tiktok_insights_store import load_state
from marketing_pipeline.tiktok.stages.extract_hooks import resolve_primary_hook

BRIEF_PATH = config.ANALYSIS_DIR / "tiktok_strategy_brief.json"
CONSTITUTION_FILES = (
    config.PLAYBOOKS_DIR / "content-instruction.md",
    config.PLAYBOOKS_DIR / "viral-format.md",
)

INSTRUCTIONS_FOR_CLAUDE = (
    "Read constitution, approved insights, and open decisions before creative suggestions. "
    "Use live cohort metrics only — do not cite view counts from recipe-2026-06.md. "
    "Never infer the channel stopped posting from an empty date filter; check meta.staleness_note. "
    "Prefer closing due decisions (list_open_decisions due_only=true) before inventing new experiments. "
    "Approve insights (Gate 1) before treating as team learning. "
    "Constitution changes (Gate 2): suggest_constitution_amendment → human approves with approve_constitution_amendment(confirmed=true). "
    "Decision outcomes require human-confirmed verdict — never invent outcomes."
)

ANTI_PATTERNS_SECTION = "Anti-patterns"


def _anti_patterns_from_playbook() -> list[str]:
    path = config.PLAYBOOKS_DIR / "viral-format.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    marker = f"## {ANTI_PATTERNS_SECTION}"
    if marker not in text:
        return []
    chunk = text.split(marker, 1)[1]
    nxt = chunk.find("\n## ")
    if nxt != -1:
        chunk = chunk[:nxt]
    return [line.strip().lstrip("- ").strip() for line in chunk.splitlines() if line.strip().startswith("-")]


def _read_playbook_excerpt(path: Path, *, max_chars: int = 4000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + 5 :]
    return text.strip()[:max_chars]


def _reference_set(dataset: TikTokMarketingDataset, *, n: int = 5) -> list[dict[str, Any]]:
    rows: list[tuple[str, Any]] = []
    for vid, rec in dataset.videos.items():
        rows.append((vid, rec))
    by_views = sorted(rows, key=lambda x: x[1].post.metrics.views or 0, reverse=True)
    by_saves = sorted(
        rows,
        key=lambda x: x[1].post.metrics.saves_per_1k_views or 0.0,
        reverse=True,
    )
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    def add(rec_tuple) -> None:
        vid, rec, reason = rec_tuple
        if vid in seen:
            return
        seen.add(vid)
        out.append(
            {
                "video_id": vid,
                "reference_reason": reason,
                "views": rec.post.metrics.views,
                "saves_per_1k_views": rec.post.metrics.saves_per_1k_views,
                "hook": resolve_primary_hook(rec.hook),
                "post_url": rec.post.url,
            }
        )

    for t in by_views[:n]:
        add((t[0], t[1], "top_views"))
    for t in by_saves[:n]:
        add((t[0], t[1], "top_saves_per_1k"))
    return out


def _registry_insights() -> list[dict[str, Any]]:
    items = []
    for entry in load_registry_pairs():
        items.append(
            {
                "group_id": entry.get("pair_id"),
                "label": entry.get("label"),
                "video_ids": entry.get("video_ids"),
                "learning": entry.get("learning"),
                "hook_pattern": entry.get("hook_pattern"),
                "confidence": entry.get("confidence"),
                "source": "variant_group_registry",
                "status": entry.get("learning_status", "approved"),
            }
        )
    return items


def build_strategy_brief(dataset: TikTokMarketingDataset) -> dict[str, Any]:
    state = load_state()
    synced = dataset.generated_at
    newest_posted = max(
        ((rec.post.posted_at or "")[:10] for rec in dataset.videos.values() if rec.post.posted_at),
        default=None,
    )

    constitution_parts = []
    for path in CONSTITUTION_FILES:
        excerpt = _read_playbook_excerpt(path)
        if excerpt:
            constitution_parts.append(f"## {path.name}\n\n{excerpt}")

    approved_insights = [
        i for i in state.get("insights", []) if i.get("status") == "approved"
    ]
    drafts = [i for i in state.get("insights", []) if i.get("status") == "draft"]
    decisions = list(state.get("decisions") or [])
    open_statuses = {"proposed", "committed", "done"}
    open_decisions = [d for d in decisions if d.get("status") in open_statuses]
    closed_decisions = [
        d for d in decisions if d.get("status") in {"outcome_recorded", "cancelled"}
    ]
    closed_decisions.sort(
        key=lambda d: d.get("closed_at") or d.get("created_at") or "",
        reverse=True,
    )

    brief: dict[str, Any] = {
        "meta": {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "metrics_as_of": synced,
            "video_count": len(dataset.videos),
            "library_newest_posted_at": newest_posted,
            "instructions_for_claude": INSTRUCTIONS_FOR_CLAUDE,
            "historical_note": (
                "recipe-2026-06.md is an 8-video cohort (June 2026) — patterns only, not current view counts."
            ),
        },
        "1_constitution": "\n\n---\n\n".join(constitution_parts),
        "2_approved_patterns": state.get("approved_patterns") or [],
        "3_approved_insights": approved_insights + _registry_insights(),
        "4_open_drafts": drafts,
        "5_anti_patterns": _anti_patterns_from_playbook(),
        "6_changelog": state.get("changelog") or [],
        "7_decisions": {
            "open": open_decisions[:15],
            "recent_closed": closed_decisions[:10],
            "open_count": len(open_decisions),
            "closed_count": len(closed_decisions),
        },
        "reference_set": _reference_set(dataset),
        "variant_groups": _registry_insights(),
    }
    return brief


def write_strategy_brief(dataset: TikTokMarketingDataset) -> Path:
    brief = build_strategy_brief(dataset)
    BRIEF_PATH.parent.mkdir(parents=True, exist_ok=True)
    BRIEF_PATH.write_text(
        __import__("json").dumps(brief, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return BRIEF_PATH
