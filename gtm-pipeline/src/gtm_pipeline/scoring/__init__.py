"""Leadership keyword scan + founder score helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Ordered by priority weight — first match wins for primary role label.
LEADERSHIP_PATTERNS: list[tuple[str, re.Pattern[str], int]] = [
    ("founder", re.compile(r"\bco[-\s]?founder\b|\bfounder\b", re.I), 40),
    ("medical_director", re.compile(r"\bmedical\s+director\b", re.I), 35),
    ("clinical_director", re.compile(r"\bclinical\s+director\b", re.I), 30),
    ("managing_director", re.compile(r"\bmanaging\s+director\b", re.I), 28),
    ("principal", re.compile(r"\bprincipal\b", re.I), 22),
    ("owner", re.compile(r"\bowner\b|\bproprietor\b", re.I), 25),
    ("lead_consultant", re.compile(r"\blead\s+consultant\b|\blead\s+clinician\b", re.I), 18),
    ("registered_manager", re.compile(r"\bregistered\s+manager\b", re.I), 15),
]


@dataclass(frozen=True)
class LeadershipHit:
    role: str
    keywords: list[str]
    weight: int
    snippets: list[str]


def scan_leadership(text: str | None) -> LeadershipHit | None:
    """Return the strongest leadership signal found in free text."""
    if not text or not text.strip():
        return None

    hits: list[tuple[str, int, str]] = []
    for role, pattern, weight in LEADERSHIP_PATTERNS:
        for m in pattern.finditer(text):
            start = max(0, m.start() - 40)
            end = min(len(text), m.end() + 40)
            snippet = re.sub(r"\s+", " ", text[start:end]).strip()
            hits.append((role, weight, snippet))

    if not hits:
        return None

    # Strongest role first; collect unique keywords
    hits.sort(key=lambda h: h[1], reverse=True)
    primary_role = hits[0][0]
    weight = hits[0][1]
    keywords = list(dict.fromkeys(h[0] for h in hits))
    snippets = list(dict.fromkeys(h[2] for h in hits))[:5]
    return LeadershipHit(role=primary_role, keywords=keywords, weight=weight, snippets=snippets)


def classify_visible_clinic_size(specialist_count: int | None) -> str:
    if specialist_count is None or specialist_count < 0:
        return "unknown"
    if specialist_count <= 1:
        return "solo"
    if specialist_count <= 3:
        return "micro"
    if specialist_count <= 9:
        return "small"
    if specialist_count <= 24:
        return "mid"
    return "large"


def compute_founder_score(
    *,
    leadership: LeadershipHit | None = None,
    visible_clinic_size: str = "unknown",
    has_cqc_rm: bool = False,
    specialist_count: int | None = None,
) -> tuple[int, str]:
    """Basic P0 founder/decision-maker attractiveness score (0–100)."""
    score = 20
    structure = "unknown"

    if leadership:
        score += leadership.weight
        structure = leadership.role

    size_bonus = {
        "solo": 25,
        "micro": 20,
        "small": 12,
        "mid": 5,
        "large": 0,
        "unknown": 0,
    }.get(visible_clinic_size, 0)
    score += size_bonus

    if has_cqc_rm:
        score += 8

    if specialist_count == 1 and leadership:
        structure = "solo_owner"
        score += 5

    return max(0, min(100, score)), structure
