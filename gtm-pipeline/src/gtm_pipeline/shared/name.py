"""Name normalisation for clinic / company matching."""

from __future__ import annotations

import re

_LEGAL_SUFFIXES = {
    "ltd",
    "limited",
    "llp",
    "plc",
    "inc",
    "llc",
    "cic",
    "company",
    "co",
}

_CLINIC_NOISE = {
    "clinic",
    "clinics",
    "centre",
    "center",
    "practice",
    "practices",
    "surgery",
    "medical",
    "health",
    "healthcare",
    "hospital",
    "hospitals",
    "consulting",
    "consultants",
    "services",
    "group",
    "the",
    "and",
    "at",
    "of",
    "for",
    "private",
    "london",
}

_TITLE_PREFIXES = {
    "mr",
    "mrs",
    "ms",
    "miss",
    "dr",
    "prof",
    "professor",
    "sir",
    "dame",
    "rev",
}


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (value or "").lower())


def normalise_name(value: str | None, *, keep_geo: bool = False) -> str:
    """Strip legal suffixes and clinic boilerplate; collapse whitespace."""
    tokens = _tokens(value or "")
    kept: list[str] = []
    for tok in tokens:
        if tok in _LEGAL_SUFFIXES:
            continue
        if tok in _CLINIC_NOISE and not (keep_geo and tok == "london"):
            continue
        kept.append(tok)
    return " ".join(kept)


def core_words(value: str | None) -> set[str]:
    """Significant tokens used for overlap scoring."""
    return {t for t in normalise_name(value).split() if len(t) > 2}


def strip_person_title(value: str | None) -> str:
    parts = (value or "").strip().split()
    while parts and parts[0].lower().rstrip(".") in _TITLE_PREFIXES:
        parts = parts[1:]
    return " ".join(parts)


def person_name_key(value: str | None) -> str:
    return " ".join(_tokens(strip_person_title(value)))
