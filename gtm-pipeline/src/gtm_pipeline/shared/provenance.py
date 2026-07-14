"""Provenance helpers for evidence-backed GTM rows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_provenance(
    *,
    source: str,
    source_url: str | None = None,
    lane: str | None = None,
    extractor: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a provenance blob attached to every upserted GTM record."""
    payload: dict[str, Any] = {
        "source": source,
        "captured_at": utc_now_iso(),
        "pipeline": "gtm-pipeline",
    }
    if source_url:
        payload["source_url"] = source_url
    if lane:
        payload["lane"] = lane
    if extractor:
        payload["extractor"] = extractor
    if extra:
        payload.update(extra)
    return payload


def evidence_item(
    *,
    kind: str,
    value: Any,
    source: str,
    source_url: str | None = None,
    confidence: float | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "kind": kind,
        "value": value,
        "source": source,
        "captured_at": utc_now_iso(),
    }
    if source_url:
        item["source_url"] = source_url
    if confidence is not None:
        item["confidence"] = confidence
    if note:
        item["note"] = note
    return item
