"""Gmail draft creation via OAuth refresh token (draft-only, never send)."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from . import config


def _credentials() -> Credentials:
    if not all([config.GMAIL_CLIENT_ID, config.GMAIL_CLIENT_SECRET, config.GMAIL_REFRESH_TOKEN]):
        raise ValueError(
            "Gmail not configured: set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN"
        )
    creds = Credentials(
        token=None,
        refresh_token=config.GMAIL_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.GMAIL_CLIENT_ID,
        client_secret=config.GMAIL_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/gmail.compose"],
    )
    creds.refresh(Request())
    return creds


def create_gmail_draft(
    *,
    subject: str,
    body: str,
    to_email: str | None = None,
) -> dict[str, Any]:
    """Create a Gmail draft. Does not send mail."""
    creds = _credentials()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    message = EmailMessage()
    message.set_content(body)
    if to_email and to_email.strip():
        message["To"] = to_email.strip()
    message["Subject"] = subject
    message["X-DocMap-MCP-Draft"] = "true"

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    draft = (
        service.users()
        .drafts()
        .create(userId="me", body={"message": {"raw": raw}})
        .execute()
    )
    return {
        "draft_id": draft.get("id"),
        "message_id": (draft.get("message") or {}).get("id"),
        "thread_id": (draft.get("message") or {}).get("threadId"),
        "status": "draft_created",
    }
