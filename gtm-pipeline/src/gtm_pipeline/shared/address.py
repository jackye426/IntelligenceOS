"""Shared address / postcode helpers (ported from GTM_B2B concepts)."""

from __future__ import annotations

import re
from dataclasses import dataclass

UK_POSTCODE_RE = re.compile(
    r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b",
    re.IGNORECASE,
)


def normalise_postcode(value: str | None) -> str:
    """Return outward+inward UK postcode uppercased with a single space, or ''."""
    if not value:
        return ""
    m = UK_POSTCODE_RE.search(str(value).upper())
    if not m:
        compact = re.sub(r"[^A-Z0-9]", "", str(value).upper())
        if re.fullmatch(r"[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2}", compact):
            return f"{compact[:-3]} {compact[-3:]}"
        return ""
    raw = re.sub(r"\s+", "", m.group(1).upper())
    return f"{raw[:-3]} {raw[-3:]}"


def postcode_outward(value: str | None) -> str:
    pc = normalise_postcode(value)
    return pc.split(" ")[0] if pc else ""


@dataclass(frozen=True)
class ParsedAddress:
    raw: str
    line: str
    city: str
    postcode: str
    street: str


def parse_address(value: str | None) -> ParsedAddress:
    """Best-effort parse of a UK clinic address / Doctify location string."""
    raw = (value or "").strip()
    if not raw:
        return ParsedAddress(raw="", line="", city="", postcode="", street="")

    # Doctify often prefixes "0.21 miles | "
    if "|" in raw:
        raw_core = raw.split("|")[-1].strip()
    else:
        raw_core = raw

    postcode = normalise_postcode(raw_core)
    without_pc = raw_core
    if postcode:
        without_pc = re.sub(re.escape(postcode.replace(" ", "")), "", without_pc, flags=re.I)
        without_pc = re.sub(re.escape(postcode), "", without_pc, flags=re.I)
        without_pc = re.sub(r",\s*$", "", without_pc).strip(" ,")

    parts = [p.strip() for p in without_pc.split(",") if p.strip()]
    street = parts[0] if parts else without_pc
    city = ""
    for part in reversed(parts[1:]):
        low = part.lower()
        if low in {"united kingdom", "uk", "england", "scotland", "wales"}:
            continue
        city = part
        break

    line = ", ".join(parts) if parts else without_pc
    return ParsedAddress(
        raw=value or "",
        line=line,
        city=city,
        postcode=postcode,
        street=street.lower(),
    )
