"""Deterministic drafting helpers for routine follow-ups."""

from __future__ import annotations

from typing import Any


def _contact_name(chase: dict[str, Any]) -> str:
    contact = chase.get("relationship_contacts") or {}
    display_name = contact.get("display_name") or contact.get("email") or "there"
    return str(display_name).split()[0] if display_name != "there" else "there"


def _subject(chase: dict[str, Any], thread: dict[str, Any] | None) -> str:
    if thread and thread.get("subject"):
        subject = str(thread["subject"])
        return subject if subject.lower().startswith("re:") else f"Re: {subject}"
    objective = chase.get("objective") or "following up"
    return f"Quick follow-up: {objective[:80]}"


def draft_followup(
    chase: dict[str, Any],
    *,
    thread: dict[str, Any] | None = None,
    tone: str = "warm",
) -> dict[str, str]:
    name = _contact_name(chase)
    objective = chase.get("objective") or "the below"
    needed = chase.get("needed_response") or "let me know what you think"
    why = chase.get("why_it_matters")

    opener = "Hope you're well."
    if tone == "concise":
        opener = "Hope all is well."
    elif tone == "friendly":
        opener = "Hope you're having a good week."

    lines = [
        f"Hi {name},",
        "",
        opener,
        "",
        f"Just wanted to follow up on {objective}.",
    ]
    if why:
        lines.append(f"It would be helpful because {why}.")
    lines.extend(
        [
            "",
            f"When you get a moment, could you {needed}?",
            "",
            "Best,",
            "Jack",
        ]
    )
    return {"subject": _subject(chase, thread), "body": "\n".join(lines)}


def brief_thread(thread: dict[str, Any]) -> dict[str, Any]:
    messages = thread.get("messages") or []
    latest = messages[-1] if messages else {}
    return {
        "gmail_thread_id": thread.get("gmail_thread_id"),
        "subject": thread.get("subject"),
        "message_count": thread.get("message_count"),
        "last_message_at": thread.get("last_message_at"),
        "latest_from": latest.get("from"),
        "latest_snippet": latest.get("snippet"),
        "participants": thread.get("participants") or [],
    }
