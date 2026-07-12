"""High-level helper for vague Relationship Desk instructions."""

from __future__ import annotations

from typing import Any

from . import act_on_chase, capture_chase, draft_chase, followup_candidates, list_chases


def run(*, instruction: str, limit: int = 10) -> dict[str, Any]:
    text = instruction.strip()
    lower = text.lower()

    if any(phrase in lower for phrase in ["who", "still need", "need to chase", "due chases", "chase today"]):
        return {
            "interpreted_as": "review_due_chases",
            "result": list_chases.due_now(limit=limit),
        }

    if any(phrase in lower for phrase in ["what follow-ups", "followup candidates", "follow-up candidates", "what did you find"]):
        return {
            "interpreted_as": "review_followup_candidates",
            "result": followup_candidates.review(limit=limit),
        }

    if any(phrase in lower for phrase in ["scan inbox", "check inbox", "find follow-ups", "find followups"]):
        return {
            "interpreted_as": "scan_inbox_for_followups",
            "result": followup_candidates.scan_inbox(max_results=limit),
        }

    if "draft" in lower and ("all" in lower or "due" in lower):
        due = list_chases.due_now(limit=limit)
        drafts = []
        for chase in due["chases"]:
            drafts.append(draft_chase.run(chase_id=chase["id"]))
        return {"interpreted_as": "draft_due_chases", "count": len(drafts), "drafts": drafts}

    if lower.startswith("chase ") or lower.startswith("follow up"):
        return {
            "interpreted_as": "capture_chase",
            "result": capture_chase.run(instruction=text, objective=text),
        }

    if "send safe" in lower:
        due = list_chases.due_now(limit=limit)
        actions = []
        for chase in due["chases"]:
            actions.append(act_on_chase.run(chase_id=chase["id"], action="send_if_safe"))
        return {"interpreted_as": "send_safe_due_chases", "count": len(actions), "actions": actions}

    return {
        "interpreted_as": "needs_more_direction",
        "message": "I can review due chases, capture a new chase, draft due chases, or send safe due chases.",
    }
