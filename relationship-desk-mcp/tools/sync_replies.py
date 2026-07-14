"""Detect replies on tracked Gmail threads."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from common import config
from common.audit import log_tool_call
from common.gmail_client import get_thread
from common.relationship_store import add_event, list_chases, update_chase


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_inbound(message: dict[str, Any], account_email: str | None) -> bool:
    sender = ((message.get("from") or {}).get("email") or "").lower()
    return bool(sender and not config.is_relationship_desk_email(sender, account_email))


def run(*, limit: int = 50) -> dict[str, Any]:
    updated: list[dict[str, Any]] = []
    try:
        chases = [
            row
            for row in list_chases(limit=limit)
            if row.get("gmail_thread_id") and row.get("status") not in {"done", "replied"}
        ]
        for chase in chases:
            thread = get_thread(chase["gmail_thread_id"], max_messages=config.MAX_THREAD_MESSAGES)
            last_contacted = _parse_iso(chase.get("last_contacted_at"))
            account_email = chase.get("account_email") or config.GMAIL_ACCOUNT_EMAIL
            inbound = []
            for message in thread.get("messages") or []:
                msg_time = _parse_iso(message.get("internal_date"))
                if _is_inbound(message, account_email) and (not last_contacted or not msg_time or msg_time >= last_contacted):
                    inbound.append(message)
            if inbound:
                latest = inbound[-1]
                chase_row = update_chase(
                    chase["id"],
                    {
                        "status": "replied",
                        "last_reply_at": latest.get("internal_date") or datetime.now(timezone.utc).isoformat(),
                    },
                )
                add_event(
                    chase_id=chase["id"],
                    event_type="replied",
                    summary=latest.get("snippet"),
                    gmail_message_id=latest.get("id"),
                )
                updated.append({"chase": chase_row, "reply": latest})
        log_tool_call(tool_name="sync_replies", request_summary=str(limit), success=True)
        return {"checked": len(chases), "updated": len(updated), "replies": updated}
    except Exception as exc:
        log_tool_call(tool_name="sync_replies", request_summary=str(limit), success=False, error=str(exc))
        raise
