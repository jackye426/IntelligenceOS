"""Supabase persistence and Intelligence OS context bridge."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import config
from .supabase_client import get_client

OPEN_STATUSES = {
    "needs_first_touch",
    "waiting",
    "needs_chase",
    "drafted",
    "sent",
    "paused",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_due_at() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=config.DEFAULT_CHASE_DAYS)).isoformat()


def _clean_email(email: str | None) -> str | None:
    if not email:
        return None
    value = email.strip().lower()
    return value or None


def _table(name: str):
    return get_client().table(name)


def upsert_contact(
    *,
    display_name: str | None = None,
    email: str | None = None,
    organization: str | None = None,
    contact_type: str = "other",
    linked_entity_type: str | None = None,
    linked_entity_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    email = _clean_email(email)
    existing = None
    if email:
        rows = (
            _table("relationship_contacts")
            .select("*")
            .eq("email", email)
            .limit(1)
            .execute()
            .data
            or []
        )
        existing = rows[0] if rows else None

    payload = {
        "display_name": display_name or (existing or {}).get("display_name") or email,
        "email": email or (existing or {}).get("email"),
        "organization": organization or (existing or {}).get("organization"),
        "contact_type": contact_type or (existing or {}).get("contact_type") or "other",
        "linked_entity_type": linked_entity_type or (existing or {}).get("linked_entity_type"),
        "linked_entity_id": linked_entity_id or (existing or {}).get("linked_entity_id"),
        "metadata": {**((existing or {}).get("metadata") or {}), **(metadata or {})},
        "updated_at": now_iso(),
    }
    if existing:
        return (
            _table("relationship_contacts")
            .update(payload)
            .eq("id", existing["id"])
            .execute()
            .data[0]
        )
    return _table("relationship_contacts").insert(payload).execute().data[0]


def search_contacts(query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    term = (query or "").strip()
    if not term:
        return []
    return (
        _table("relationship_contacts")
        .select("*")
        .or_(f"display_name.ilike.*{term}*,email.ilike.*{term}*,organization.ilike.*{term}*")
        .limit(limit)
        .execute()
        .data
        or []
    )


def search_practitioners(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    term = (query or "").strip()
    if not term:
        return []
    fields = "id,name,email,specialty,specialties,practice_name,clinic_name,website,profile_url"
    try:
        rows = (
            _table(config.PRACTITIONERS_TABLE)
            .select(fields)
            .or_(f"name.ilike.*{term}*,email.ilike.*{term}*,specialty.ilike.*{term}*")
            .limit(limit)
            .execute()
            .data
            or []
        )
    except Exception:
        rows = (
            _table(config.PRACTITIONERS_TABLE)
            .select("*")
            .or_(f"name.ilike.*{term}*,email.ilike.*{term}*")
            .limit(limit)
            .execute()
            .data
            or []
        )
    return [
        {
            "source": config.PRACTITIONERS_TABLE,
            "linked_entity_type": "practitioner",
            "linked_entity_id": str(row.get("id")),
            "display_name": row.get("name") or row.get("display_name"),
            "email": _clean_email(row.get("email")),
            "organization": row.get("practice_name") or row.get("clinic_name"),
            "metadata": row,
        }
        for row in rows
    ]


def search_clinics(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    term = (query or "").strip()
    if not term:
        return []
    try:
        rows = (
            _table("clinic_accounts")
            .select("id,name,email,website,status,metadata")
            .or_(f"name.ilike.*{term}*,email.ilike.*{term}*")
            .limit(limit)
            .execute()
            .data
            or []
        )
    except Exception:
        return []
    return [
        {
            "source": "clinic_accounts",
            "linked_entity_type": "clinic_account",
            "linked_entity_id": str(row.get("id")),
            "display_name": row.get("name"),
            "email": _clean_email(row.get("email")),
            "organization": row.get("name"),
            "metadata": row,
        }
        for row in rows
    ]


def resolve_contact_hint(
    hint: str | None = None,
    *,
    email: str | None = None,
) -> dict[str, Any]:
    if email:
        matches = search_contacts(email, limit=1)
        if matches:
            return {"matched": True, "contact": matches[0], "candidates": matches}

    candidates: list[dict[str, Any]] = []
    if hint:
        candidates.extend(search_contacts(hint, limit=5))
        candidates.extend(search_practitioners(hint, limit=5))
        candidates.extend(search_clinics(hint, limit=5))

    return {
        "matched": len(candidates) == 1,
        "contact": candidates[0] if len(candidates) == 1 else None,
        "candidates": candidates,
    }


def create_chase(
    *,
    objective: str,
    contact_id: str | None = None,
    contact_hint: str | None = None,
    email: str | None = None,
    gmail_thread_id: str | None = None,
    account_email: str | None = None,
    why_it_matters: str | None = None,
    needed_response: str | None = None,
    next_action: str | None = None,
    next_chase_due_at: str | None = None,
    urgency: str = "normal",
    send_mode: str = "requires_approval",
    notes: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not contact_id and (email or contact_hint):
        resolved = resolve_contact_hint(contact_hint, email=email)
        contact = resolved.get("contact")
        if contact and contact.get("source") in {config.PRACTITIONERS_TABLE, "clinic_accounts"}:
            contact = upsert_contact(
                display_name=contact.get("display_name") or contact_hint,
                email=contact.get("email") or email,
                organization=contact.get("organization"),
                contact_type="practitioner"
                if contact.get("linked_entity_type") == "practitioner"
                else "clinic",
                linked_entity_type=contact.get("linked_entity_type"),
                linked_entity_id=contact.get("linked_entity_id"),
                metadata={"source_context": contact.get("metadata") or {}},
            )
        elif not contact and (email or contact_hint):
            contact = upsert_contact(display_name=contact_hint or email, email=email)
        if contact:
            contact_id = contact.get("id")

    payload = {
        "contact_id": contact_id,
        "gmail_thread_id": gmail_thread_id,
        "account_email": account_email or config.GMAIL_ACCOUNT_EMAIL,
        "objective": objective,
        "why_it_matters": why_it_matters,
        "needed_response": needed_response,
        "status": "needs_chase",
        "next_action": next_action or "follow_up",
        "next_chase_due_at": next_chase_due_at or default_due_at(),
        "urgency": urgency,
        "send_mode": send_mode,
        "notes": notes,
        "metadata": metadata or {},
    }
    chase = _table("relationship_chases").insert(payload).execute().data[0]
    add_event(chase_id=chase["id"], event_type="created", summary=objective)
    return chase


def get_chase(chase_id: str) -> dict[str, Any]:
    rows = (
        _table("relationship_chases")
        .select("*, relationship_contacts(*)")
        .eq("id", chase_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise ValueError(f"Unknown chase_id: {chase_id}")
    return rows[0]


def list_chases(
    *,
    status: str | None = None,
    due_before: str | None = None,
    limit: int = 50,
    include_done: bool = False,
) -> list[dict[str, Any]]:
    query = (
        _table("relationship_chases")
        .select("*, relationship_contacts(*)")
        .order("next_chase_due_at", desc=False, nullsfirst=False)
        .limit(max(1, min(limit, 100)))
    )
    if status:
        query = query.eq("status", status)
    elif not include_done:
        query = query.in_("status", list(OPEN_STATUSES))
    if due_before:
        query = query.lte("next_chase_due_at", due_before)
    return query.execute().data or []


def update_chase(chase_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    fields = {k: v for k, v in fields.items() if v is not None}
    fields["updated_at"] = now_iso()
    rows = _table("relationship_chases").update(fields).eq("id", chase_id).execute().data or []
    if not rows:
        raise ValueError(f"Unknown chase_id: {chase_id}")
    return rows[0]


def add_event(
    *,
    chase_id: str,
    event_type: str,
    summary: str | None = None,
    gmail_message_id: str | None = None,
    gmail_draft_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "chase_id": chase_id,
        "event_type": event_type,
        "summary": summary,
        "gmail_message_id": gmail_message_id,
        "gmail_draft_id": gmail_draft_id,
        "metadata": metadata or {},
    }
    return _table("relationship_events").insert(payload).execute().data[0]


def list_events(chase_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    return (
        _table("relationship_events")
        .select("*")
        .eq("chase_id", chase_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
