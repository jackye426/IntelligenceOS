"""Deterministic follow-up classifier for Gmail threads."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import config

AUTOMATED_SENDERS = {
    "no-reply",
    "noreply",
    "notifications",
    "notification",
    "mailer-daemon",
    "postmaster",
}

NOISE_TERMS = {
    "unsubscribe",
    "newsletter",
    "privacy policy",
    "marketing preferences",
    "view in browser",
    "automatic reply",
    "out of office",
}

ASK_TERMS = {
    "?",
    "can you",
    "could you",
    "please send",
    "please share",
    "let me know",
    "would you",
    "are you able",
    "do you have",
    "when can",
    "confirm",
}

PROMISE_TERMS = {
    "i will",
    "i'll",
    "we will",
    "we'll",
    "will send",
    "send over",
    "get back to you",
    "come back to you",
    "follow up",
}

REPLY_NEED_TERMS = {
    "can i",
    "could i",
    "please can",
    "would you be able",
    "what do you need",
    "happy to",
    "interested",
    "sounds good",
    "yes",
}


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


def _contains_any(text: str, terms: set[str]) -> bool:
    lower = text.lower()
    return any(term in lower for term in terms)


def _is_automated(message: dict[str, Any], subject: str) -> bool:
    sender = ((message.get("from") or {}).get("email") or "").lower()
    local = sender.split("@", 1)[0]
    body = f"{subject} {message.get('snippet') or ''} {message.get('body') or ''}".lower()
    return (
        any(term in local for term in AUTOMATED_SENDERS)
        or _contains_any(body, NOISE_TERMS)
        or "List-Unsubscribe" in (message.get("labels") or [])
    )


def _is_outbound(message: dict[str, Any], account_email: str | None) -> bool:
    sender = ((message.get("from") or {}).get("email") or "").lower()
    return bool(account_email and sender == account_email.lower())


def _is_inbound(message: dict[str, Any], account_email: str | None) -> bool:
    sender = ((message.get("from") or {}).get("email") or "").lower()
    return bool(sender and account_email and sender != account_email.lower())


def _message_text(message: dict[str, Any]) -> str:
    return f"{message.get('subject') or ''}\n{message.get('snippet') or ''}\n{message.get('body') or ''}"


def classify_thread(
    thread: dict[str, Any],
    *,
    contact_match: dict[str, Any] | None = None,
    stale_after_days: int = 5,
) -> dict[str, Any]:
    messages = thread.get("messages") or []
    if not messages:
        return {
            "should_follow_up": False,
            "classification": "no_action",
            "reason": "Thread has no readable messages.",
            "confidence": 0.0,
            "risk_level": "uncertain",
        }

    account_email = config.GMAIL_ACCOUNT_EMAIL
    latest = messages[-1]
    subject = thread.get("subject") or latest.get("subject") or "(no subject)"
    latest_text = _message_text(latest)
    latest_at = _parse_iso(latest.get("internal_date")) or datetime.now(timezone.utc)
    age_days = max(0, (datetime.now(timezone.utc) - latest_at).days)
    contact_confidence = float((contact_match or {}).get("confidence") or 0.0)
    known_contact = contact_confidence >= 0.7

    if _is_automated(latest, subject):
        return {
            "should_follow_up": False,
            "classification": "no_action",
            "reason": "Latest message looks automated or promotional.",
            "confidence": 0.1,
            "risk_level": "safe",
        }

    if _is_outbound(latest, account_email):
        asked = _contains_any(latest_text, ASK_TERMS)
        if asked and age_days >= stale_after_days:
            confidence = 0.72 + (0.18 if known_contact else 0.0)
            return {
                "should_follow_up": True,
                "classification": "waiting_on_them",
                "reason": f"We asked for something {age_days} days ago and there is no newer inbound reply.",
                "suggested_objective": f"Follow up on: {subject}",
                "suggested_needed_response": "reply with the update or answer we asked for",
                "confidence": min(confidence, 0.95),
                "risk_level": "safe" if known_contact else "uncertain",
                "due_at": datetime.now(timezone.utc).isoformat(),
            }
        return {
            "should_follow_up": False,
            "classification": "no_action",
            "reason": "Latest message is outbound, but it is not old enough or does not contain a clear ask.",
            "confidence": 0.25,
            "risk_level": "safe",
        }

    if _is_inbound(latest, account_email):
        if _contains_any(latest_text, REPLY_NEED_TERMS | ASK_TERMS):
            confidence = 0.68 + (0.17 if known_contact else 0.0)
            return {
                "should_follow_up": True,
                "classification": "they_need_us",
                "reason": "Latest inbound message appears to need a reply from us.",
                "suggested_objective": f"Reply to: {subject}",
                "suggested_needed_response": "send a response or next step",
                "confidence": min(confidence, 0.9),
                "risk_level": "uncertain",
                "due_at": datetime.now(timezone.utc).isoformat(),
            }
        if _contains_any(latest_text, PROMISE_TERMS) and age_days >= stale_after_days:
            confidence = 0.7 + (0.15 if known_contact else 0.0)
            return {
                "should_follow_up": True,
                "classification": "waiting_on_them",
                "reason": f"They appeared to promise a next step {age_days} days ago.",
                "suggested_objective": f"Check progress on: {subject}",
                "suggested_needed_response": "send the promised update or material",
                "confidence": min(confidence, 0.9),
                "risk_level": "safe" if known_contact else "uncertain",
                "due_at": datetime.now(timezone.utc).isoformat(),
            }

    return {
        "should_follow_up": False,
        "classification": "no_action",
        "reason": "No clear follow-up pattern found.",
        "confidence": 0.2 + (0.1 if known_contact else 0.0),
        "risk_level": "safe" if known_contact else "uncertain",
        "due_at": (datetime.now(timezone.utc) + timedelta(days=stale_after_days)).isoformat(),
    }
