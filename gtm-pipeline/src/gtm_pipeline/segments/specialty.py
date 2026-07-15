"""Map noisy Doctify / CQC specialty strings → canonical keys for cohorts."""

from __future__ import annotations

import re
from typing import Iterable

# canonical_key -> substrings that map to it (lowercased match)
_CANONICAL_PATTERNS: dict[str, tuple[str, ...]] = {
    "obstetrics_gynaecology": (
        "obstetrics",
        "gynaecology",
        "gynecology",
        "obgyn",
        "ob/gyn",
        "o&g",
    ),
    "fertility": (
        "fertility",
        "reproductive medicine",
        "andrology",
    ),
    "ivf": (
        "ivf",
        "in vitro",
        "egg freezing",
        "embryo",
    ),
    "menopause": ("menopause", "perimenopause", "hrt"),
    "endometriosis": ("endometriosis", "endo "),
    "dermatology": ("dermatology", "dermatolog", "skin clinic"),
    "cardiology": ("cardiology",),
    "general_practice": ("general practice", "gp)", "(gp)", " family medicine"),
    "mental_health": ("mental health", "psychiatr", "psycholog"),
    "ophthalmology": ("ophthalmology", "eye clinic", "optometr"),
    "urology": ("urology",),
    "dental": ("dental", "dentist", "orthodont"),
}


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def specialty_to_keys(label: str) -> list[str]:
    """Return zero or more canonical keys for a raw specialty label."""
    text = _norm_text(label)
    if not text:
        return []
    keys: list[str] = []
    for key, pats in _CANONICAL_PATTERNS.items():
        for p in pats:
            if p in text:
                keys.append(key)
                break
    return keys


def tags_to_keys(tags: Iterable[str] | None) -> set[str]:
    out: set[str] = set()
    for t in tags or []:
        out.update(specialty_to_keys(str(t)))
    return out


def primary_specialty_label(tags: Iterable[str] | None, preferred_keys: set[str] | None = None) -> str:
    """Pick a display primary specialty; prefer tags matching preferred_keys."""
    tags_list = [str(t).strip() for t in (tags or []) if str(t).strip()]
    if not tags_list:
        return ""
    if preferred_keys:
        for t in tags_list:
            if set(specialty_to_keys(t)) & preferred_keys:
                return t
    return tags_list[0]


def clinic_specialty_keys(
    specialties: Iterable[str] | None,
    cqc_specialisms: Iterable[str] | None = None,
    people_specialties: Iterable[str] | None = None,
) -> set[str]:
    keys = tags_to_keys(specialties)
    keys |= tags_to_keys(cqc_specialisms)
    keys |= tags_to_keys(people_specialties)
    return keys
