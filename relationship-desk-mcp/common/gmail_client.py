"""Gmail read/draft/send helpers for Relationship Desk."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from . import config


def _credentials() -> Credentials:
    if not all([config.GMAIL_CLIENT_ID, config.GMAIL_CLIENT_SECRET, config.GMAIL_REFRESH_TOKEN]):
        raise ValueError(
            "Gmail not configured: set RELATIONSHIP_GMAIL_CLIENT_ID, "
            "RELATIONSHIP_GMAIL_CLIENT_SECRET, RELATIONSHIP_GMAIL_REFRESH_TOKEN"
        )
    creds = Credentials(
        token=None,
        refresh_token=config.GMAIL_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.GMAIL_CLIENT_ID,
        client_secret=config.GMAIL_CLIENT_SECRET,
        scopes=[
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.modify",
        ],
    )
    creds.refresh(Request())
    return creds


def get_service():
    return build("gmail", "v1", credentials=_credentials(), cache_discovery=False)


def _header(message: dict[str, Any], name: str) -> str:
    headers = (message.get("payload") or {}).get("headers") or []
    for item in headers:
        if (item.get("name") or "").lower() == name.lower():
            return (item.get("value") or "").strip()
    return ""


def _decode_body_data(value: str) -> str:
    try:
        return base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _body_plain(payload: dict[str, Any]) -> str:
    if not payload:
        return ""
    body = payload.get("body") or {}
    if body.get("data"):
        return _decode_body_data(body["data"])
    for part in payload.get("parts") or []:
        if (part.get("mimeType") or "").lower() == "text/plain":
            data = ((part.get("body") or {}).get("data")) or ""
            if data:
                return _decode_body_data(data)
        nested = _body_plain(part)
        if nested:
            return nested
    return ""


def _timestamp(message: dict[str, Any]) -> str | None:
    internal = message.get("internalDate")
    if not internal:
        return None
    try:
        return datetime.fromtimestamp(int(internal) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def _participant(value: str) -> dict[str, str]:
    name, email = parseaddr(value or "")
    return {"name": name, "email": email.lower()}


def message_summary(message: dict[str, Any], *, include_body: bool = True) -> dict[str, Any]:
    body = _body_plain(message.get("payload") or {}) if include_body else ""
    return {
        "id": message.get("id"),
        "thread_id": message.get("threadId"),
        "subject": _header(message, "Subject"),
        "from": _participant(_header(message, "From")),
        "to": [_participant(p.strip()) for p in _header(message, "To").split(",") if p.strip()],
        "cc": [_participant(p.strip()) for p in _header(message, "Cc").split(",") if p.strip()],
        "date": _header(message, "Date"),
        "internal_date": _timestamp(message),
        "labels": message.get("labelIds") or [],
        "snippet": message.get("snippet"),
        "body": body[:4000],
    }


def search_threads(query: str, *, max_results: int = 10) -> list[dict[str, Any]]:
    service = get_service()
    response = (
        service.users()
        .threads()
        .list(userId="me", q=query, maxResults=max(1, min(max_results, 50)))
        .execute()
    )
    threads = []
    for item in response.get("threads") or []:
        full = (
            service.users()
            .threads()
            .get(userId="me", id=item["id"], format="metadata")
            .execute()
        )
        messages = full.get("messages") or []
        latest = messages[-1] if messages else {}
        threads.append(
            {
                "gmail_thread_id": item["id"],
                "message_count": len(messages),
                "subject": _header(latest, "Subject"),
                "snippet": latest.get("snippet"),
                "last_message_at": _timestamp(latest),
                "participants": [
                    message_summary(m, include_body=False).get("from") for m in messages[-5:]
                ],
            }
        )
    return threads


def get_thread(gmail_thread_id: str, *, max_messages: int | None = None) -> dict[str, Any]:
    service = get_service()
    thread = (
        service.users()
        .threads()
        .get(userId="me", id=gmail_thread_id, format="full")
        .execute()
    )
    messages = thread.get("messages") or []
    if max_messages is not None:
        messages = messages[-max_messages:]
    summaries = [message_summary(m) for m in messages]
    return {
        "gmail_thread_id": gmail_thread_id,
        "message_count": len(thread.get("messages") or []),
        "messages": summaries,
        "subject": summaries[-1].get("subject") if summaries else None,
        "last_message_at": summaries[-1].get("internal_date") if summaries else None,
        "participants": _participants_from_messages(summaries),
    }


def _participants_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for msg in messages:
        people = [msg.get("from") or {}] + list(msg.get("to") or []) + list(msg.get("cc") or [])
        for person in people:
            email = (person.get("email") or "").lower()
            if email and email not in seen:
                seen.add(email)
                out.append({"name": person.get("name") or "", "email": email})
    return out


def create_draft(
    *,
    subject: str,
    body: str,
    to_email: str | None = None,
    thread_id: str | None = None,
    from_email: str | None = None,
) -> dict[str, Any]:
    service = get_service()
    send_as_email = config.resolve_send_as_email(from_email)
    message = EmailMessage()
    message.set_content(body)
    if send_as_email:
        message["From"] = send_as_email
    if to_email:
        message["To"] = to_email
    message["Subject"] = subject
    message["X-DocMap-Relationship-Desk"] = "true"
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    payload: dict[str, Any] = {"message": {"raw": raw}}
    if thread_id:
        payload["message"]["threadId"] = thread_id
    draft = service.users().drafts().create(userId="me", body=payload).execute()
    return {
        "draft_id": draft.get("id"),
        "message_id": (draft.get("message") or {}).get("id"),
        "thread_id": (draft.get("message") or {}).get("threadId"),
        "status": "draft_created",
    }


def send_message(
    *,
    subject: str,
    body: str,
    to_email: str,
    thread_id: str | None = None,
    from_email: str | None = None,
) -> dict[str, Any]:
    service = get_service()
    send_as_email = config.resolve_send_as_email(from_email)
    message = EmailMessage()
    message.set_content(body)
    if send_as_email:
        message["From"] = send_as_email
    message["To"] = to_email
    message["Subject"] = subject
    message["X-DocMap-Relationship-Desk"] = "true"
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    payload: dict[str, Any] = {"raw": raw}
    if thread_id:
        payload["threadId"] = thread_id
    sent = service.users().messages().send(userId="me", body=payload).execute()
    return {
        "message_id": sent.get("id"),
        "thread_id": sent.get("threadId"),
        "status": "sent",
    }
