"""Deterministic doctor/brand screen. Ambiguous bios are flagged for LLM."""

from __future__ import annotations

import re
from typing import Any

SCREEN_VERSION = "screen_v1"

POSITIVE = re.compile(
    r"\b(dr|doctor|surgeon|consultant|gp|physician|gynaecolog|gynecolog|"
    r"obstetric|dermatolog|urolog|gastroenterolog|colorectal|fertility|"
    r"endometriosis|nhs|gmc)\b",
    re.I,
)
NEGATIVE_NON_MEDICAL = re.compile(
    r"\b(dentist|dental|physio|physiotherap|veterinar|vet\b|nurse|nursing|"
    r"phd\b|professor of (?:history|english|law))\b",
    re.I,
)
BRAND = re.compile(
    r"\b(clinic\b|hospital\b|group\b|aesthetics? clinic|medspa|wellness brand)\b",
    re.I,
)
STUDENT = re.compile(r"\b(student|med student|medical student|fy1|fy2)\b", re.I)
QUALIFIED = re.compile(r"\b(consultant|attending|board[- ]certified|gmc|frcs|mrcog|mrcgp)\b", re.I)


def has_medical_signal(nickname: str | None, signature: str | None) -> bool:
    blob = f"{nickname or ''} {signature or ''}"
    return bool(POSITIVE.search(blob))


def screen_profile(
    *,
    nickname: str | None,
    bio: str | None,
    video_count: int | None,
    is_organization: bool | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    blob = f"{nickname or ''} {bio or ''}"

    if is_organization or (BRAND.search(blob) and not POSITIVE.search(blob)):
        reasons.append("brand_or_org")
    if video_count is not None and video_count < 3:
        reasons.append("too_few_videos")
    if NEGATIVE_NON_MEDICAL.search(blob) and not POSITIVE.search(blob):
        reasons.append("non_medical_doctor_token")
    if STUDENT.search(blob) and not QUALIFIED.search(blob):
        reasons.append("student_without_qualified_signal")

    positive = bool(POSITIVE.search(blob))
    if reasons:
        return {
            "screen_result": "exclude",
            "screen_reasons": reasons,
            "ambiguous": False,
            "screen_version": SCREEN_VERSION,
        }
    if not positive:
        return {
            "screen_result": "ambiguous",
            "screen_reasons": ["no_clear_doctor_token"],
            "ambiguous": True,
            "screen_version": SCREEN_VERSION,
        }
    return {
        "screen_result": "include",
        "screen_reasons": ["doctor_token"],
        "ambiguous": False,
        "screen_version": SCREEN_VERSION,
    }
