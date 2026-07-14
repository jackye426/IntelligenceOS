"""Numeric match confidence with explainable reasons."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse

from gtm_pipeline.shared.address import normalise_postcode, parse_address, postcode_outward
from gtm_pipeline.shared.name import core_words, normalise_name, person_name_key


def _digits(phone: str | None) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("44") and len(digits) > 10:
        digits = "0" + digits[2:]
    return digits


def _phone_score(a: str | None, b: str | None) -> float:
    da, db = _digits(a), _digits(b)
    if not da or not db:
        return 0.0
    if da == db:
        return 1.0
    # Compare last 10 / 9 digits (UK mobiles / landlines)
    if da[-10:] == db[-10:] or da[-9:] == db[-9:]:
        return 0.95
    if da[-7:] == db[-7:]:
        return 0.6
    return 0.0


def _name_score(a: str | None, b: str | None) -> float:
    na, nb = normalise_name(a), normalise_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    wa, wb = core_words(a), core_words(b)
    if wa and wb:
        overlap = len(wa & wb) / max(len(wa), len(wb))
    else:
        overlap = 0.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    # Containment bonus (short brand inside longer CQC name)
    contain = 0.0
    if na in nb or nb in na:
        contain = 0.85
    return max(overlap, ratio, contain)


def _geo_score(candidate: dict[str, Any], target: dict[str, Any]) -> float:
    c_pc = normalise_postcode(candidate.get("postcode") or candidate.get("address") or "")
    t_pc = normalise_postcode(target.get("postcode") or target.get("address") or "")
    if c_pc and t_pc:
        if c_pc == t_pc:
            return 1.0
        if postcode_outward(c_pc) == postcode_outward(t_pc):
            return 0.7
        if c_pc[:2] == t_pc[:2]:
            return 0.35
        return 0.0

    c_addr = parse_address(candidate.get("address") or "")
    t_addr = parse_address(target.get("address") or "")
    if c_addr.street and t_addr.street and c_addr.street == t_addr.street:
        return 0.8
    if c_addr.city and t_addr.city and c_addr.city.lower() == t_addr.city.lower():
        return 0.4
    return 0.0


def _website_score(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0

    def host(url: str) -> str:
        try:
            parsed = urlparse(url if "://" in url else f"https://{url}")
        except ValueError:
            return ""
        return parsed.netloc.lower().removeprefix("www.")

    ha, hb = host(a), host(b)
    if not ha or not hb:
        return 0.0
    if ha == hb:
        return 1.0
    if ha in hb or hb in ha:
        return 0.8
    return 0.0


@dataclass
class MatchResult:
    confidence: float
    reasons: list[str] = field(default_factory=list)
    components: dict[str, float] = field(default_factory=dict)
    phone_present: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def match_confidence(candidate: dict[str, Any], target: dict[str, Any]) -> MatchResult:
    """Score a candidate against a target clinic/person record.

    Weights (when phone present on either side with a usable value):
      phone 50% / name 30% / geo 20%
    Else:
      name 80% / geo 20%

    Website/phone extras are recorded in reasons and can nudge confidence.
    """
    phone_s = _phone_score(candidate.get("phone"), target.get("phone"))
    name_s = _name_score(candidate.get("name"), target.get("name"))
    geo_s = _geo_score(candidate, target)
    web_s = _website_score(candidate.get("website"), target.get("website"))

    phone_present = bool(_digits(candidate.get("phone")) and _digits(target.get("phone")))

    reasons: list[str] = []
    if phone_present:
        conf = 0.50 * phone_s + 0.30 * name_s + 0.20 * geo_s
        reasons.append(f"phone={phone_s:.2f}*0.50")
        reasons.append(f"name={name_s:.2f}*0.30")
        reasons.append(f"geo={geo_s:.2f}*0.20")
    else:
        conf = 0.80 * name_s + 0.20 * geo_s
        reasons.append(f"name={name_s:.2f}*0.80")
        reasons.append(f"geo={geo_s:.2f}*0.20")

    if web_s >= 0.8:
        # Soft bonus capped so website alone cannot auto-accept a weak name match.
        bonus = min(0.10, 0.10 * web_s)
        conf = min(1.0, conf + bonus)
        reasons.append(f"website_bonus=+{bonus:.2f}")

    # Person-name path: if both look like people, blend person similarity.
    if candidate.get("person_name") or target.get("person_name"):
        p_score = SequenceMatcher(
            None,
            person_name_key(candidate.get("person_name") or candidate.get("name")),
            person_name_key(target.get("person_name") or target.get("name")),
        ).ratio()
        conf = max(conf, p_score)
        reasons.append(f"person_name={p_score:.2f}")

    return MatchResult(
        confidence=round(min(1.0, conf), 4),
        reasons=reasons,
        components={
            "phone": round(phone_s, 4),
            "name": round(name_s, 4),
            "geo": round(geo_s, 4),
            "website": round(web_s, 4),
        },
        phone_present=phone_present,
    )
