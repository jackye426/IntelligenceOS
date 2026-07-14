"""Gate 2: consent-gated constitution amendments (playbook writes + auto-embed)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from common import config
from common.audit import log_tool_call
from tools.playbook_embed import sync_playbook_content
from tools.tiktok_strategy_state import fetch_strategy_row, save_strategy_metadata

AmendmentStatus = Literal["pending", "approved", "rejected"]

ALLOWED_TARGETS = frozenset({"content-instruction.md", "viral-format.md"})
HOOK_SECTION = "Hook & packaging rules (from approved A/B learnings)"
ANTI_PATTERNS_SECTION = "Anti-patterns"

BUNDLED_PLAYBOOKS_DIR = Path(__file__).resolve().parents[1] / "data" / "playbooks"


def _repo_playbooks_dir() -> Path:
    return config.REPO_ROOT / "marketing-pipeline" / "tiktok" / "data" / "playbooks"


def _validate_target(target_section: str) -> None:
    if target_section not in ALLOWED_TARGETS:
        raise ValueError(
            f"target_section must be one of {sorted(ALLOWED_TARGETS)}, got {target_section!r}"
        )


def _normalize_bullet(text: str) -> str:
    return text.strip().lstrip("- ").strip()


def _amendments_list(meta: dict[str, Any]) -> list[dict[str, Any]]:
    return list(meta.get("constitution_amendments") or [])


def _load_meta() -> dict[str, Any]:
    row = fetch_strategy_row()
    return dict((row or {}).get("metadata") or {})


def _save_meta(meta: dict[str, Any]) -> None:
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_strategy_metadata(meta)


def _read_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _load_playbook_from_disk(filename: str) -> str:
    for base in (_repo_playbooks_dir(), BUNDLED_PLAYBOOKS_DIR):
        text = _read_file(base / filename)
        if text:
            return text
    return ""


def _ensure_playbook_files(meta: dict[str, Any]) -> dict[str, str]:
    files = dict(meta.get("playbook_files") or {})
    changed = False
    for name in ALLOWED_TARGETS:
        if not files.get(name):
            disk = _load_playbook_from_disk(name)
            if disk:
                files[name] = disk
                changed = True
    if changed:
        meta["playbook_files"] = files
    return files


def _write_playbook_to_disk(filename: str, content: str) -> list[str]:
    """Best-effort write for local dev / git. Returns paths written."""
    written: list[str] = []
    for base in (_repo_playbooks_dir(), BUNDLED_PLAYBOOKS_DIR):
        try:
            path = base / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            written.append(str(path))
        except OSError:
            continue
    return written


def append_bullet_to_markdown(
    text: str,
    *,
    section_title: str,
    bullet: str,
) -> tuple[str, bool]:
    """Return updated markdown and whether a new bullet was added."""
    bullet_line = f"- {_normalize_bullet(bullet)}"
    if bullet_line in text:
        return text, False

    heading = f"## {section_title}"
    if heading not in text:
        updated = text.rstrip() + f"\n\n{heading}\n\n{bullet_line}\n"
        return updated, True

    parts = text.split(heading, 1)
    before = parts[0]
    after = parts[1]
    next_h = after.find("\n## ")
    if next_h == -1:
        section_body = after
        rest = ""
    else:
        section_body = after[:next_h]
        rest = after[next_h:]

    updated = f"{before}{heading}{section_body.rstrip()}\n{bullet_line}\n{rest}"
    return updated, True


def append_bullet_to_section(
    file_path: Path,
    *,
    section_title: str,
    bullet: str,
) -> bool:
    """Append a bullet under ## section_title in a file. Returns False if duplicate."""
    text = _read_file(file_path)
    updated, added = append_bullet_to_markdown(
        text, section_title=section_title, bullet=bullet
    )
    if not added:
        return False
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(updated, encoding="utf-8")
    return True


def _section_for_target(target_section: str, proposed_bullet: str) -> str:
    if target_section == "viral-format.md":
        lower = proposed_bullet.lower()
        if "anti" in lower or "avoid" in lower or "do not" in lower:
            return ANTI_PATTERNS_SECTION
        return HOOK_SECTION
    return "Standing rules"


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5 :].strip()
    return text.strip()


def _excerpt(text: str, *, max_chars: int = 4000) -> str:
    return _strip_frontmatter(text)[:max_chars]


def _anti_patterns_from_text(text: str) -> list[str]:
    marker = f"## {ANTI_PATTERNS_SECTION}"
    if marker not in text:
        return []
    chunk = text.split(marker, 1)[1]
    nxt = chunk.find("\n## ")
    if nxt != -1:
        chunk = chunk[:nxt]
    return [_normalize_bullet(line) for line in chunk.splitlines() if line.strip().startswith("- ")]


def _refresh_brief_constitution(meta: dict[str, Any]) -> None:
    files = _ensure_playbook_files(meta)
    brief = dict(meta.get("strategy_brief") or {})
    parts: list[str] = []
    for name in ("content-instruction.md", "viral-format.md"):
        content = files.get(name) or _load_playbook_from_disk(name)
        excerpt = _excerpt(content)
        if excerpt:
            parts.append(f"## {name}\n\n{excerpt}")
    brief["1_constitution"] = "\n\n---\n\n".join(parts)
    brief["5_anti_patterns"] = _anti_patterns_from_text(
        files.get("viral-format.md") or _load_playbook_from_disk("viral-format.md")
    )
    meta["strategy_brief"] = brief


def _apply_playbook_amendment(
    meta: dict[str, Any],
    *,
    filename: str,
    section: str,
    bullet: str,
) -> tuple[bool, dict[str, Any]]:
    files = _ensure_playbook_files(meta)
    current = files.get(filename) or _load_playbook_from_disk(filename)
    updated, added = append_bullet_to_markdown(current, section_title=section, bullet=bullet)
    files[filename] = updated
    meta["playbook_files"] = files
    disk_paths = _write_playbook_to_disk(filename, updated)
    embed = sync_playbook_content(filename=filename, content=updated)
    return added, {"disk_paths": disk_paths, "embed": embed}


def suggest_constitution_amendment(
    *,
    proposed_bullet: str,
    target_section: str = "viral-format.md",
    rationale: str = "",
    insight_id: str | None = None,
    source_group_id: str | None = None,
    suggested_by: str = "model",
) -> dict[str, Any]:
    """Propose a constitution amendment (pending until human approves)."""
    summary = f"target={target_section}, insight={insight_id}"
    try:
        _validate_target(target_section)
        meta = _load_meta()
        _ensure_playbook_files(meta)
        insights = list(meta.get("insights") or [])

        if insight_id:
            insight = next((i for i in insights if i.get("insight_id") == insight_id), None)
            if not insight:
                return {"ok": False, "error": f"insight_id {insight_id} not found"}
            if insight.get("status") not in ("approved", "promoted"):
                return {
                    "ok": False,
                    "error": "Insight must be approved (Gate 1) before constitution promotion.",
                }
            source_group_id = source_group_id or insight.get("group_id")

        amendment_id = f"ca_{uuid4().hex[:10]}"
        entry = {
            "amendment_id": amendment_id,
            "status": "pending",
            "proposed_bullet": _normalize_bullet(proposed_bullet),
            "target_section": target_section,
            "playbook_section": _section_for_target(target_section, proposed_bullet),
            "rationale": rationale.strip(),
            "insight_id": insight_id,
            "source_group_id": source_group_id,
            "suggested_at": datetime.now(timezone.utc).isoformat(),
            "suggested_by": suggested_by,
            "approved_at": None,
            "approved_by": None,
            "rejected_at": None,
            "reject_reason": None,
        }
        amendments = _amendments_list(meta)
        amendments.append(entry)
        meta["constitution_amendments"] = amendments
        _save_meta(meta)

        result = {
            "ok": True,
            "amendment": entry,
            "next_step": "Call approve_constitution_amendment(amendment_id, confirmed=true) to apply.",
        }
        log_tool_call(
            tool_name="suggest_constitution_amendment",
            request_summary=summary,
            success=True,
            action_type="write",
            metadata={"amendment_id": amendment_id},
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="suggest_constitution_amendment",
            request_summary=summary,
            success=False,
            error=str(exc),
            action_type="write",
        )
        raise


def list_constitution_amendments(
    *,
    status: AmendmentStatus | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    meta = _load_meta()
    items = _amendments_list(meta)
    if status:
        items = [a for a in items if a.get("status") == status]
    pending = [a for a in _amendments_list(meta) if a.get("status") == "pending"]
    return {
        "amendments": items[:limit],
        "count": len(items),
        "pending_count": len(pending),
    }


def approve_constitution_amendment(
    amendment_id: str,
    *,
    confirmed: bool = False,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Apply amendment: update playbook, Supabase metadata, embeddings, brief — one step."""
    summary = f"amendment_id={amendment_id}, confirmed={confirmed}"
    if not confirmed:
        return {
            "ok": False,
            "error": "Set confirmed=true after human explicitly approves this amendment.",
        }
    try:
        meta = _load_meta()
        insights = list(meta.get("insights") or [])
        amendments = _amendments_list(meta)
        target = next((a for a in amendments if a.get("amendment_id") == amendment_id), None)
        if not target:
            return {"ok": False, "error": f"amendment_id {amendment_id} not found"}
        if target.get("status") != "pending":
            return {"ok": False, "error": f"Amendment status is {target.get('status')}, not pending."}

        filename = str(target["target_section"])
        section = str(
            target.get("playbook_section") or _section_for_target(filename, target["proposed_bullet"])
        )
        added, apply_info = _apply_playbook_amendment(
            meta,
            filename=filename,
            section=section,
            bullet=str(target["proposed_bullet"]),
        )

        now = datetime.now(timezone.utc).isoformat()
        target["status"] = "approved"
        target["approved_at"] = now
        target["approved_by"] = approved_by
        meta["constitution_amendments"] = amendments

        insight_id = target.get("insight_id")
        if insight_id:
            for entry in insights:
                if entry.get("insight_id") == insight_id:
                    entry["status"] = "promoted"
                    entry["promoted_at"] = now
                    break
            meta["insights"] = insights

        changelog = list(meta.get("changelog") or [])
        line = (
            f"{now[:10]}: [constitution] {target['proposed_bullet'][:120]}"
            + (f" (from {target.get('source_group_id')})" if target.get("source_group_id") else "")
        )
        changelog.append(line)
        meta["changelog"] = changelog

        _refresh_brief_constitution(meta)
        _save_meta(meta)

        result = {
            "ok": True,
            "amendment": target,
            "playbook_file": filename,
            "duplicate_skipped": not added,
            "embed": apply_info.get("embed"),
            "note": "Done — playbook updated in Supabase, embeddings refreshed, brief excerpt rebuilt.",
        }
        log_tool_call(
            tool_name="approve_constitution_amendment",
            request_summary=summary,
            success=True,
            action_type="write",
            metadata={"amendment_id": amendment_id},
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="approve_constitution_amendment",
            request_summary=summary,
            success=False,
            error=str(exc),
            action_type="write",
        )
        raise


def reject_constitution_amendment(
    amendment_id: str,
    *,
    reason: str = "",
) -> dict[str, Any]:
    summary = f"amendment_id={amendment_id}"
    try:
        meta = _load_meta()
        amendments = _amendments_list(meta)
        target = next((a for a in amendments if a.get("amendment_id") == amendment_id), None)
        if not target:
            return {"ok": False, "error": f"amendment_id {amendment_id} not found"}
        if target.get("status") != "pending":
            return {"ok": False, "error": f"Amendment status is {target.get('status')}, not pending."}

        target["status"] = "rejected"
        target["rejected_at"] = datetime.now(timezone.utc).isoformat()
        target["reject_reason"] = reason.strip() or None
        meta["constitution_amendments"] = amendments
        _save_meta(meta)

        log_tool_call(
            tool_name="reject_constitution_amendment",
            request_summary=summary,
            success=True,
            action_type="write",
        )
        return {"ok": True, "amendment": target}
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="reject_constitution_amendment",
            request_summary=summary,
            success=False,
            error=str(exc),
            action_type="write",
        )
        raise
