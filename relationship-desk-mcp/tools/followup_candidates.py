"""Follow-up candidate MCP tools."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from common.audit import log_tool_call
from common.candidate_store import (
    convert_candidate_to_chase,
    ignore_candidate,
    list_candidates,
    resolve_sender_contact,
    set_worker_state,
    upsert_candidate,
    update_candidate,
)
from common.followup_classifier import classify_thread
from common.gmail_client import get_thread, search_threads


def _gmail_after_date(hours_back: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    return f"{dt.year}/{dt.month}/{dt.day}"


def _latest_external_sender(thread: dict[str, Any], account_email: str | None) -> dict[str, str]:
    from common import config

    for message in reversed(thread.get("messages") or []):
        sender = message.get("from") or {}
        email = (sender.get("email") or "").lower()
        if email and not config.is_relationship_desk_email(email, account_email):
            return {"email": email, "name": sender.get("name") or ""}
    return {"email": "", "name": ""}


def scan_inbox(
    *,
    since: str | None = None,
    hours_back: int = 72,
    max_results: int = 30,
    auto_convert_high_confidence: bool = False,
    min_confidence: float = 0.65,
    auto_convert_confidence: float = 0.88,
) -> dict[str, Any]:
    from common import config

    query = f"in:inbox after:{since or _gmail_after_date(hours_back)}"
    created_or_updated: list[dict[str, Any]] = []
    converted: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []

    try:
        summaries = search_threads(query, max_results=max_results)
        for summary in summaries:
            thread = get_thread(summary["gmail_thread_id"])
            sender = _latest_external_sender(thread, config.GMAIL_ACCOUNT_EMAIL)
            contact_match = resolve_sender_contact(
                sender_email=sender.get("email"),
                sender_name=sender.get("name"),
            )
            classification = classify_thread(thread, contact_match=contact_match)
            latest = (thread.get("messages") or [{}])[-1]
            if not classification.get("should_follow_up") or classification.get("confidence", 0) < min_confidence:
                ignored.append(
                    {
                        "gmail_thread_id": thread.get("gmail_thread_id"),
                        "classification": classification,
                    }
                )
                continue

            contact = contact_match.get("contact") or {}
            candidate = upsert_candidate(
                {
                    "gmail_thread_id": thread["gmail_thread_id"],
                    "gmail_message_id": latest.get("id"),
                    "contact_id": contact.get("id"),
                    "sender_email": sender.get("email"),
                    "sender_name": sender.get("name"),
                    "subject": thread.get("subject"),
                    "classification": classification["classification"],
                    "reason": classification["reason"],
                    "suggested_objective": classification.get("suggested_objective"),
                    "suggested_needed_response": classification.get("suggested_needed_response"),
                    "confidence": classification.get("confidence"),
                    "risk_level": classification.get("risk_level"),
                    "due_at": classification.get("due_at"),
                    "evidence": {
                        "latest_message": {
                            "id": latest.get("id"),
                            "from": latest.get("from"),
                            "internal_date": latest.get("internal_date"),
                            "snippet": latest.get("snippet"),
                        },
                        "contact_match": contact_match,
                        "thread_summary": summary,
                    },
                    "metadata": {"source": "scan_inbox_for_followups"},
                }
            )
            created_or_updated.append(candidate)

            if (
                auto_convert_high_confidence
                and (candidate.get("confidence") or 0) >= auto_convert_confidence
                and candidate.get("risk_level") == "safe"
                and candidate.get("contact_id")
            ):
                converted.append(convert_candidate_to_chase(candidate["id"]))

        set_worker_state(
            "last_followup_scan",
            {
                "query": query,
                "scanned_at": datetime.now(timezone.utc).isoformat(),
                "threads_seen": len(summaries),
                "candidates": len(created_or_updated),
                "converted": len(converted),
            },
        )
        log_tool_call(tool_name="scan_inbox_for_followups", request_summary=query, success=True)
        return {
            "query": query,
            "threads_seen": len(summaries),
            "candidates": created_or_updated,
            "ignored_count": len(ignored),
            "converted": converted,
        }
    except Exception as exc:
        log_tool_call(tool_name="scan_inbox_for_followups", request_summary=query, success=False, error=str(exc))
        raise


def review(
    *,
    status: str = "suggested",
    limit: int = 30,
    min_confidence: float | None = None,
) -> dict[str, Any]:
    try:
        candidates = list_candidates(status=status, limit=limit, min_confidence=min_confidence)
        log_tool_call(tool_name="review_followup_candidates", request_summary=status, success=True)
        return {"status": status, "count": len(candidates), "candidates": candidates}
    except Exception as exc:
        log_tool_call(tool_name="review_followup_candidates", request_summary=status, success=False, error=str(exc))
        raise


def accept(candidate_id: str) -> dict[str, Any]:
    try:
        result = convert_candidate_to_chase(candidate_id)
        log_tool_call(
            tool_name="accept_followup_candidate",
            request_summary=candidate_id,
            success=True,
            entity_type="relationship_followup_candidate",
            entity_id=candidate_id,
            action_type="write",
        )
        return result
    except Exception as exc:
        log_tool_call(tool_name="accept_followup_candidate", request_summary=candidate_id, success=False, error=str(exc))
        raise


def ignore(candidate_id: str, reason: str | None = None) -> dict[str, Any]:
    try:
        candidate = ignore_candidate(candidate_id, reason=reason)
        log_tool_call(
            tool_name="ignore_followup_candidate",
            request_summary=candidate_id,
            success=True,
            entity_type="relationship_followup_candidate",
            entity_id=candidate_id,
            action_type="write",
        )
        return {"candidate": candidate}
    except Exception as exc:
        log_tool_call(tool_name="ignore_followup_candidate", request_summary=candidate_id, success=False, error=str(exc))
        raise


def mark_accepted(candidate_id: str) -> dict[str, Any]:
    try:
        candidate = update_candidate(candidate_id, {"status": "accepted"})
        log_tool_call(
            tool_name="mark_followup_candidate_accepted",
            request_summary=candidate_id,
            success=True,
            entity_type="relationship_followup_candidate",
            entity_id=candidate_id,
            action_type="write",
        )
        return {"candidate": candidate}
    except Exception as exc:
        log_tool_call(tool_name="mark_followup_candidate_accepted", request_summary=candidate_id, success=False, error=str(exc))
        raise
