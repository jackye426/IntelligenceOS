"""Safety classification for relationship actions."""

from __future__ import annotations

from . import config

RISKY_TERMS = {
    "diagnosis",
    "treatment",
    "medical advice",
    "guarantee",
    "guaranteed",
    "price",
    "pricing",
    "contract",
    "legal",
    "patient details",
    "confidential",
    "attachment",
}


def classify_message(*, body: str, to_email: str | None, objective: str | None) -> dict:
    lower = f"{body or ''} {objective or ''}".lower()
    reasons: list[str] = []
    if not to_email:
        reasons.append("missing recipient")
    for term in RISKY_TERMS:
        if term in lower:
            reasons.append(f"contains risky term: {term}")
    if len(body or "") > 2500:
        reasons.append("message is unusually long")
    if reasons:
        return {"safety_level": "risky", "safe_to_send": False, "reasons": reasons}
    if not objective:
        return {
            "safety_level": "uncertain",
            "safe_to_send": False,
            "reasons": ["missing objective"],
        }
    return {"safety_level": "safe", "safe_to_send": True, "reasons": []}


def mode_allows_send(*, confirmed: bool, safe_to_send: bool) -> bool:
    mode = config.DESK_MODE
    if mode == "draft_only":
        return False
    if mode == "supervised_send":
        return confirmed
    if mode == "auto_send_safe":
        return safe_to_send or confirmed
    return False

