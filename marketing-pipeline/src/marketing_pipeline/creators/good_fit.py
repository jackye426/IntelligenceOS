"""Good-fit predicate (versioned, deterministic)."""

from __future__ import annotations

from typing import Any

GOOD_FIT_VERSION = "good_fit_v1"

PRIORITY_SPECIALTIES = frozenset(
    {
        "obstetrics_gynaecology",
        "fertility",
        "menopause",
        "endometriosis",
        "ivf",
        "dermatology",
        "colorectal",
        "general_surgery",
        "gastroenterology",
        "urology",
        "general_practice",
    }
)


def is_good_fit(profile: dict[str, Any]) -> bool:
    if not profile.get("is_doctor"):
        return False
    conf = profile.get("doctor_confidence")
    if conf is None or float(conf) < 0.8:
        return False
    if profile.get("lane") not in {"research", "both", "customer"}:
        return False
    if profile.get("do_not_contact"):
        return False
    if profile.get("hydrate_status") != "complete":
        return False
    research_eligible = bool(profile.get("research_eligible"))
    customer_eligible = bool(profile.get("customer_eligible"))
    growth = profile.get("growth_intent_level") or 0
    return research_eligible or (customer_eligible and int(growth) >= 2)


def deep_priority(profile: dict[str, Any], *, on_demand: bool = False) -> int:
    if on_demand:
        return 100
    lane = profile.get("lane")
    if lane in {"customer", "both"} or (
        (profile.get("geo_country") or "").upper() == "GB"
        and profile.get("practice_setting") in {"private", "mixed"}
    ):
        return 80
    if profile.get("specialty_key") in PRIORITY_SPECIALTIES:
        return 60
    if profile.get("research_eligible"):
        return 40
    return 20
