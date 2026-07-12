"""Persistence helpers for follow-up candidates and worker state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .relationship_store import (
    create_chase,
    now_iso,
    search_clinics,
    search_contacts,
    search_practitioners,
    upsert_contact,
)
from .supabase_client import get_client


def _table(name: str):
    return get_client().table(name)


def _clean_email(email: str | None) -> str | None:
    if not email:
        return None
    value = email.strip().lower()
    return value or None


def _first_exact_email(candidates: list[dict[str, Any]], email: str | None) -> dict[str, Any] | None:
    if not email:
        return None
    email = email.lower()
    for item in candidates:
        if (item.get("email") or "").lower() == email:
            return item
    return None


def resolve_sender_contact(
    *,
    sender_email: str | None,
    sender_name: str | None = None,
) -> dict[str, Any]:
    """Resolve an email participant to Relationship Desk or Intelligence OS context."""
    sender_email = _clean_email(sender_email)
    candidates: list[dict[str, Any]] = []

    if sender_email:
        candidates.extend(search_contacts(sender_email, limit=5))
        exact = _first_exact_email(candidates, sender_email)
        if exact:
            return {"matched": True, "confidence": 1.0, "contact": exact, "candidates": candidates}

        practitioners = search_practitioners(sender_email, limit=5)
        candidates.extend(practitioners)
        exact = _first_exact_email(practitioners, sender_email)
        if exact:
            contact = upsert_contact(
                display_name=exact.get("display_name") or sender_name or sender_email,
                email=sender_email,
                organization=exact.get("organization"),
                contact_type="practitioner",
                linked_entity_type=exact.get("linked_entity_type"),
                linked_entity_id=exact.get("linked_entity_id"),
                metadata={"source_context": exact.get("metadata") or {}},
            )
            return {"matched": True, "confidence": 0.95, "contact": contact, "candidates": candidates}

        clinics = search_clinics(sender_email, limit=5)
        candidates.extend(clinics)
        exact = _first_exact_email(clinics, sender_email)
        if exact:
            contact = upsert_contact(
                display_name=exact.get("display_name") or sender_name or sender_email,
                email=sender_email,
                organization=exact.get("organization"),
                contact_type="clinic",
                linked_entity_type=exact.get("linked_entity_type"),
                linked_entity_id=exact.get("linked_entity_id"),
                metadata={"source_context": exact.get("metadata") or {}},
            )
            return {"matched": True, "confidence": 0.9, "contact": contact, "candidates": candidates}

    if sender_name:
        candidates.extend(search_contacts(sender_name, limit=5))
        candidates.extend(search_practitioners(sender_name, limit=5))
        candidates.extend(search_clinics(sender_name, limit=5))

    return {
        "matched": len(candidates) == 1,
        "confidence": 0.7 if len(candidates) == 1 else 0.0,
        "contact": candidates[0] if len(candidates) == 1 else None,
        "candidates": candidates,
    }


def upsert_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Create or refresh the active candidate for a Gmail thread."""
    gmail_thread_id = candidate["gmail_thread_id"]
    existing = (
        _table("relationship_followup_candidates")
        .select("*")
        .eq("gmail_thread_id", gmail_thread_id)
        .in_("status", ["suggested", "accepted"])
        .limit(1)
        .execute()
        .data
        or []
    )
    payload = {k: v for k, v in candidate.items() if v is not None}
    payload["updated_at"] = now_iso()
    if existing:
        return (
            _table("relationship_followup_candidates")
            .update(payload)
            .eq("id", existing[0]["id"])
            .execute()
            .data[0]
        )
    return _table("relationship_followup_candidates").insert(payload).execute().data[0]


def list_candidates(
    *,
    status: str = "suggested",
    limit: int = 30,
    min_confidence: float | None = None,
) -> list[dict[str, Any]]:
    query = (
        _table("relationship_followup_candidates")
        .select("*, relationship_contacts(*)")
        .eq("status", status)
        .order("confidence", desc=True)
        .order("due_at", desc=False, nullsfirst=False)
        .limit(max(1, min(limit, 100)))
    )
    if min_confidence is not None:
        query = query.gte("confidence", min_confidence)
    return query.execute().data or []


def get_candidate(candidate_id: str) -> dict[str, Any]:
    rows = (
        _table("relationship_followup_candidates")
        .select("*, relationship_contacts(*)")
        .eq("id", candidate_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise ValueError(f"Unknown candidate_id: {candidate_id}")
    return rows[0]


def update_candidate(candidate_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    payload = {k: v for k, v in fields.items() if v is not None}
    payload["updated_at"] = now_iso()
    rows = (
        _table("relationship_followup_candidates")
        .update(payload)
        .eq("id", candidate_id)
        .execute()
        .data
        or []
    )
    if not rows:
        raise ValueError(f"Unknown candidate_id: {candidate_id}")
    return rows[0]


def ignore_candidate(candidate_id: str, *, reason: str | None = None) -> dict[str, Any]:
    candidate = get_candidate(candidate_id)
    metadata = candidate.get("metadata") or {}
    metadata["ignored_reason"] = reason
    return update_candidate(candidate_id, {"status": "ignored", "metadata": metadata})


def convert_candidate_to_chase(candidate_id: str) -> dict[str, Any]:
    candidate = get_candidate(candidate_id)
    contact = candidate.get("relationship_contacts") or {}
    chase = create_chase(
        objective=candidate.get("suggested_objective") or candidate.get("reason"),
        contact_id=candidate.get("contact_id"),
        contact_hint=contact.get("display_name") or candidate.get("sender_name"),
        email=contact.get("email") or candidate.get("sender_email"),
        gmail_thread_id=candidate.get("gmail_thread_id"),
        why_it_matters=candidate.get("reason"),
        needed_response=candidate.get("suggested_needed_response"),
        next_chase_due_at=candidate.get("due_at"),
        urgency="normal" if (candidate.get("confidence") or 0) < 0.9 else "high",
        metadata={
            "source": "followup_candidate",
            "candidate_id": candidate_id,
            "evidence": candidate.get("evidence") or {},
        },
    )
    updated = update_candidate(
        candidate_id,
        {
            "status": "converted",
            "converted_chase_id": chase["id"],
        },
    )
    return {"candidate": updated, "chase": chase}


def get_worker_state(key: str) -> dict[str, Any] | None:
    rows = (
        _table("relationship_worker_state")
        .select("*")
        .eq("key", key)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def set_worker_state(key: str, value: dict[str, Any]) -> dict[str, Any]:
    existing = get_worker_state(key)
    payload = {
        "key": key,
        "value": value,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if existing:
        return _table("relationship_worker_state").update(payload).eq("key", key).execute().data[0]
    return _table("relationship_worker_state").insert(payload).execute().data[0]
