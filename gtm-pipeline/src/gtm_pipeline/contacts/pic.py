"""Person-in-charge selection for outreach contacts.

Product order: CQC nominated individual → registered manager → founder / high-priority.
Existing emails are preferred as the outreach address once PIC is chosen, but do not
override PIC role order (unlike cohort best-person which historically ranked email first).
"""

from __future__ import annotations

import re
from typing import Any


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _role_rank(role: str) -> int:
    r = (role or "").lower().strip()
    if r == "nominated_individual":
        return 100
    if r == "registered_manager":
        return 90
    if r in {"founder", "owner"} or "founder" in r or "owner" in r or "director" in r:
        return 80
    if r == "specialist":
        return 40
    return 50


def _name_match(a: str, b: str) -> bool:
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # last-token overlap (Dr Jane Smith vs Jane Smith)
    ta, tb = na.split(), nb.split()
    if ta and tb and ta[-1] == tb[-1] and len(ta[-1]) > 2:
        return True
    return False


def pick_person_in_charge(
    people: list[dict[str, Any]],
    *,
    cqc_nominated_individual: str = "",
    cqc_registered_manager: str = "",
) -> dict[str, Any] | None:
    """Return the best PIC person row, or None if no people."""
    if not people:
        return None

    ni = (cqc_nominated_individual or "").strip()
    rm = (cqc_registered_manager or "").strip()

    # Prefer exact role rows first
    for role in ("nominated_individual", "registered_manager"):
        role_people = [p for p in people if (p.get("role") or "").lower() == role]
        if role_people:
            # Among role, prefer one with email then higher priority
            return max(
                role_people,
                key=lambda p: (
                    1 if (p.get("email") or "").strip() else 0,
                    int(p.get("priority") or 0),
                ),
            )

    # Match CQC name strings onto people cards
    for name, synthetic_role in ((ni, "nominated_individual"), (rm, "registered_manager")):
        if not name:
            continue
        matches = [p for p in people if _name_match(p.get("full_name") or "", name)]
        if matches:
            best = max(
                matches,
                key=lambda p: (
                    1 if (p.get("email") or "").strip() else 0,
                    int(p.get("priority") or 0),
                ),
            )
            # Annotate effective role for contact materialization
            out = dict(best)
            out["_effective_role"] = synthetic_role
            return out

    # Founder / high-priority / leadership
    return max(
        people,
        key=lambda p: (
            _role_rank(p.get("role") or ""),
            int(p.get("priority") or 0),
            1 if (p.get("email") or "").strip() else 0,
            1 if (p.get("linkedin_url") or "").strip() else 0,
        ),
    )


def synthetic_pic_from_cqc(
    *,
    cqc_nominated_individual: str = "",
    cqc_registered_manager: str = "",
) -> dict[str, Any] | None:
    """Build a synthetic PIC dict when no people row exists but CQC names do."""
    ni = (cqc_nominated_individual or "").strip()
    rm = (cqc_registered_manager or "").strip()
    if ni:
        return {
            "id": None,
            "full_name": ni,
            "role": "nominated_individual",
            "email": None,
            "linkedin_url": None,
            "linkedin_status": None,
            "priority": 95,
        }
    if rm:
        return {
            "id": None,
            "full_name": rm,
            "role": "registered_manager",
            "email": None,
            "linkedin_url": None,
            "linkedin_status": None,
            "priority": 90,
        }
    return None


def infer_email_source(person: dict[str, Any] | None, email: str) -> str:
    if not (email or "").strip():
        return "none"
    if not person:
        return "doctify"
    prov = person.get("provenance") or {}
    src = (prov.get("source") or "").lower() if isinstance(prov, dict) else ""
    if "people_enrich" in src or "practitioner" in src:
        return "practitioner"
    role = (person.get("role") or "").lower()
    if role in {"nominated_individual", "registered_manager"}:
        # Usually from enrich path when email present
        return "practitioner"
    return "practitioner"


def derive_preferred_channel(*, email: str | None, linkedin_url: str | None) -> str:
    if (email or "").strip():
        return "email"
    if (linkedin_url or "").strip():
        return "linkedin"
    return "none"


def derive_contact_status(
    *,
    email: str | None,
    linkedin_url: str | None,
    rocketreach_status: str | None,
    linkedin_status: str | None,
) -> str:
    if (rocketreach_status or "") == "ambiguous" or (linkedin_status or "") == "ambiguous":
        return "needs_review"
    if (email or "").strip() or (linkedin_url or "").strip():
        return "ready"
    return "needs_enrichment"
