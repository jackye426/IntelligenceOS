"""Relationship context assembly for evidence-led briefs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import config
from .drafting import brief_thread
from .gmail_client import get_thread, search_threads
from .relationship_store import (
    get_chase,
    list_contact_chases,
    list_context_sources,
    list_events,
    list_memory_items,
    resolve_contact_hint,
    upsert_context_source,
)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _source_id(source: dict[str, Any]) -> str:
    return f"{source.get('source_type')}:{source.get('source_id')}"


def _dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for source in sources:
        key = _source_id(source)
        if key not in seen:
            out.append(source)
            seen.add(key)
    return out


def _context_quality(
    *,
    gmail_count: int,
    calendar_count: int,
    drive_count: int,
    memory_count: int,
    contact_known: bool,
) -> str:
    if gmail_count and calendar_count and (drive_count or memory_count):
        return "rich"
    if gmail_count and (calendar_count or drive_count or memory_count):
        return "good"
    if gmail_count:
        return "email-only"
    if calendar_count:
        return "calendar-only"
    if contact_known:
        return "sparse"
    return "unknown"


def _timeline_item(
    *,
    kind: str,
    title: str | None,
    occurred_at: str | None,
    summary: str | None,
    source_id: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "title": title,
        "occurred_at": occurred_at,
        "summary": summary,
        "source_id": source_id,
    }


def _search_gmail_for_contact(contact: dict[str, Any], *, days_back: int, limit: int) -> list[dict[str, Any]]:
    email = contact.get("email")
    name = contact.get("display_name")
    terms = []
    if email:
        terms.append(f"from:({email}) OR to:({email})")
    if name:
        terms.append(f'"{name}"')
    if not terms:
        return []
    since = datetime.now(timezone.utc) - timedelta(days=max(1, days_back))
    query = f"({' OR '.join(terms)}) after:{since.year}/{since.month}/{since.day}"
    try:
        return search_threads(query, max_results=limit)
    except Exception:
        return []


def build_context(
    *,
    contact_hint: str | None = None,
    email: str | None = None,
    chase_id: str | None = None,
    days_back: int = 180,
    include_live_gmail: bool = True,
    max_threads: int = 5,
) -> dict[str, Any]:
    chase = get_chase(chase_id) if chase_id else None
    contact = (chase or {}).get("relationship_contacts") or None
    if not contact:
        resolved = resolve_contact_hint(contact_hint, email=email)
        contact = resolved.get("contact")
    contact_known = bool(contact and contact.get("id"))

    chases: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    if chase:
        chases.append(chase)
        events = list_events(chase["id"], limit=20)
    elif contact_known:
        chases = list_contact_chases(contact["id"], limit=20)
        for item in chases[:5]:
            events.extend(list_events(item["id"], limit=5))

    stored_sources = list_context_sources(contact["id"], limit=30) if contact_known else []
    memory_items = list_memory_items(contact["id"], limit=30) if contact_known else []

    gmail_threads: list[dict[str, Any]] = []
    if include_live_gmail:
        if chase and chase.get("gmail_thread_id"):
            try:
                thread = get_thread(chase["gmail_thread_id"], max_messages=config.MAX_THREAD_MESSAGES)
                gmail_threads.append({"brief": brief_thread(thread), "thread": thread})
            except Exception:
                pass
        elif contact:
            for summary in _search_gmail_for_contact(contact, days_back=days_back, limit=max_threads):
                gmail_threads.append({"brief": summary, "thread": None})

    live_sources: list[dict[str, Any]] = []
    for item in gmail_threads:
        brief = item.get("brief") or {}
        source = {
            "source_type": "gmail_thread",
            "source_id": brief.get("gmail_thread_id"),
            "title": brief.get("subject"),
            "occurred_at": brief.get("last_message_at"),
            "participants": brief.get("participants") or [],
            "context_quality": "email-only",
            "metadata": {"message_count": brief.get("message_count")},
        }
        if source["source_id"]:
            live_sources.append(source)
            if contact_known:
                upsert_context_source(contact_id=contact["id"], **source)

    sources = _dedupe_sources([*stored_sources, *live_sources])
    gmail_count = len([s for s in sources if s.get("source_type") in {"gmail_thread", "gmail_message"}])
    calendar_count = len([s for s in sources if s.get("source_type") == "calendar_event"])
    drive_count = len([s for s in sources if s.get("source_type") in {"drive_file", "call_transcript"}])
    quality = _context_quality(
        gmail_count=gmail_count,
        calendar_count=calendar_count,
        drive_count=drive_count,
        memory_count=len(memory_items),
        contact_known=contact_known,
    )

    timeline = []
    for item in chases:
        timeline.append(
            _timeline_item(
                kind="chase",
                title=item.get("objective"),
                occurred_at=item.get("created_at"),
                summary=item.get("needed_response") or item.get("why_it_matters"),
                source_id=item.get("id"),
            )
        )
    for source in sources:
        timeline.append(
            _timeline_item(
                kind=source.get("source_type"),
                title=source.get("title"),
                occurred_at=source.get("occurred_at") or source.get("last_seen_at"),
                summary=(source.get("metadata") or {}).get("summary"),
                source_id=source.get("source_id"),
            )
        )
    timeline.sort(key=lambda item: _parse_iso(item.get("occurred_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    open_loops = [
        item for item in memory_items if item.get("memory_type") in {"open_loop", "commitment", "next_action"}
    ]
    do_not_mention = [item for item in memory_items if item.get("memory_type") == "do_not_mention"]

    missing_evidence: list[str] = []
    if not gmail_count:
        missing_evidence.append("No Gmail thread context found.")
    if not calendar_count:
        missing_evidence.append("No Calendar meeting context indexed yet.")
    if not drive_count:
        missing_evidence.append("No Drive notes or transcripts indexed yet.")

    safe_angle = "Follow up only on explicit chase details and available email evidence."
    if quality in {"rich", "good"}:
        safe_angle = "Use the open loops and cited source evidence; avoid uncited meeting claims."
    elif quality == "sparse":
        safe_angle = "Use a neutral first-touch or clarification note."

    return {
        "contact": contact,
        "context_quality": quality,
        "sources_summary": {
            "gmail_threads": gmail_count,
            "calendar_events": calendar_count,
            "drive_or_transcript_items": drive_count,
            "memory_items": len(memory_items),
        },
        "current_chases": chases,
        "recent_events": events[:20],
        "timeline": timeline[:30],
        "memory_items": memory_items,
        "open_loops": open_loops,
        "do_not_mention": do_not_mention,
        "gmail_threads": gmail_threads,
        "sources": sources,
        "missing_evidence": missing_evidence,
        "safe_followup_angle": safe_angle,
        "drafting_guidance": {
            "may_reference": [
                "explicit chase objective",
                "contact identity",
                "Gmail thread content returned in this context",
                "active memory items with evidence",
            ],
            "avoid_referencing": [
                "meeting details without Calendar/Drive/transcript evidence",
                "verbal commitments not present in source evidence",
                "patient-sensitive details",
            ],
        },
    }
