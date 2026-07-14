"""Match CQC Registered Manager / Nominated Individual names to practitioners."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from typing import Any

from gtm_pipeline.shared.match_confidence import match_confidence
from gtm_pipeline.shared.name import person_name_key, strip_person_title
from gtm_pipeline.shared.supabase_client import get_client, supabase_configured

logger = logging.getLogger(__name__)


@dataclass
class PersonMatch:
    query_name: str
    role: str  # registered_manager | nominated_individual
    practitioner_id: str | None = None
    matched_name: str = ""
    email: str = ""
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _token_score(a: str, b: str) -> float:
    ka, kb = person_name_key(a), person_name_key(b)
    if not ka or not kb:
        return 0.0
    if ka == kb:
        return 1.0
    ta, tb = ka.split(), kb.split()
    sa, sb = set(ta), set(tb)
    if not sa or not sb:
        return 0.0
    # Last-name gate: require shared final token when both have 2+ parts
    if len(ta) >= 2 and len(tb) >= 2:
        if ta[-1] != tb[-1]:
            return 0.0
        # First + last align (middle names may differ) — strong match
        if ta[0] == tb[0]:
            return 0.93
    overlap = len(sa & sb) / max(len(sa), len(sb))
    ratio = SequenceMatcher(None, ka, kb).ratio()
    return max(overlap, ratio)


def score_person_pair(cqc_name: str, practitioner_name: str) -> float:
    return _token_score(cqc_name, practitioner_name)


def match_cqc_people_to_candidates(
    *,
    registered_manager: str = "",
    nominated_individual: str = "",
    candidates: list[dict[str, Any]],
    min_confidence: float = 0.82,
) -> list[PersonMatch]:
    """Match CQC role names against an in-memory candidate list.

    Each candidate dict should include ``full_name`` and optionally
    ``id`` / ``practitioner_id`` / ``email``.
    """
    queries: list[tuple[str, str]] = []
    if nominated_individual and nominated_individual.strip():
        queries.append(("nominated_individual", nominated_individual.strip()))
    if registered_manager and registered_manager.strip():
        # Avoid duplicate query when RM == NI
        if person_name_key(registered_manager) != person_name_key(nominated_individual):
            queries.append(("registered_manager", registered_manager.strip()))
        elif not nominated_individual.strip():
            queries.append(("registered_manager", registered_manager.strip()))

    results: list[PersonMatch] = []
    for role, qname in queries:
        best: PersonMatch | None = None
        for cand in candidates:
            cname = cand.get("full_name") or cand.get("name") or ""
            score = score_person_pair(qname, cname)
            if score < min_confidence:
                continue
            # Soft blend with match_confidence person path for explainability
            mc = match_confidence(
                {"person_name": cname, "name": cname},
                {"person_name": qname, "name": qname},
            )
            conf = round(max(score, mc.confidence), 4)
            hit = PersonMatch(
                query_name=qname,
                role=role,
                practitioner_id=str(
                    cand.get("practitioner_id") or cand.get("id") or ""
                )
                or None,
                matched_name=cname,
                email=str(cand.get("email") or ""),
                confidence=conf,
                reasons=[f"token={score:.2f}", *mc.reasons[:2]],
            )
            if best is None or hit.confidence > best.confidence:
                best = hit
        if best:
            results.append(best)
        else:
            results.append(
                PersonMatch(query_name=qname, role=role, reasons=["no_candidate_above_threshold"])
            )
    return results


def match_cqc_people_against_practitioners(
    *,
    registered_manager: str = "",
    nominated_individual: str = "",
    limit_per_query: int = 25,
    min_confidence: float = 0.82,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Lookup practitioners in Supabase by last-name ilike, then score."""
    names = [n for n in (nominated_individual, registered_manager) if n and n.strip()]
    if not names:
        return {"matches": [], "candidates_fetched": 0}

    if dry_run or not supabase_configured():
        return {
            "dry_run": True,
            "matches": [
                PersonMatch(query_name=n, role="lookup", reasons=["dry_run"]).as_dict()
                for n in names
            ],
            "candidates_fetched": 0,
        }

    client = get_client()
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n in names:
        key = person_name_key(n)
        parts = key.split()
        if not parts:
            continue
        last = parts[-1]
        rows = (
            client.table("integrated_practitioners")
            .select("id, name, first_name, last_name, email, title, specialty")
            .ilike("name", f"%{last}%")
            .limit(limit_per_query)
            .execute()
            .data
            or []
        )
        for row in rows:
            pid = str(row.get("id") or "")
            if pid and pid in seen:
                continue
            if pid:
                seen.add(pid)
            full = (row.get("name") or "").strip()
            if not full:
                parts = [row.get("first_name") or "", row.get("last_name") or ""]
                full = " ".join(p for p in parts if p).strip()
            candidates.append(
                {
                    "practitioner_id": pid,
                    "full_name": full,
                    "email": row.get("email") or "",
                    "title": row.get("title") or "",
                    "specialty": row.get("specialty") or "",
                }
            )

    matches = match_cqc_people_to_candidates(
        registered_manager=registered_manager,
        nominated_individual=nominated_individual,
        candidates=candidates,
        min_confidence=min_confidence,
    )
    return {
        "matches": [m.as_dict() for m in matches],
        "candidates_fetched": len(candidates),
    }


def resolve_person(name: str, clinic_hint: str = "") -> dict:
    """Back-compat stub entry — prefer match_cqc_people_against_practitioners."""
    stripped = strip_person_title(name)
    result = match_cqc_people_against_practitioners(
        nominated_individual=stripped,
        dry_run=not supabase_configured(),
    )
    return {"status": "ok", "name": name, "clinic_hint": clinic_hint, **result}
