"""Seed the golden @drleewarren content_guidelines_v1 as a confirmed brief."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from marketing_pipeline.creators.paths import normalise_handle, pending_tiktok_user_id
from marketing_pipeline.creators.store import get_store
from marketing_pipeline.creators.write_brief import GUIDELINES_SCHEMA, REQUIRED_SECTIONS, validate_artefact

HANDLE = "drleewarren"
HEADING_RE = re.compile(r"^##\s+(\d+)\.\s+(.*)$", re.M)


def golden_path() -> Path:
    return Path(__file__).resolve().parents[4] / "docs" / "examples" / "drleewarren-content-guidelines.md"


def parse_golden_markdown(text: str) -> dict[str, Any]:
    matches = list(HEADING_RE.finditer(text))
    sections: dict[str, Any] = {}
    for i, match in enumerate(matches):
        key = match.group(1)
        title = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        sections[key] = {
            "title": title,
            "body": body,
            "epistemic": "measured" if "*Measured*" in body or "*measured*" in body.lower() else "inferred",
        }
    for key in REQUIRED_SECTIONS:
        sections.setdefault(key, {"title": f"section_{key}", "body": "", "epistemic": "inferred"})
    artefact = {
        "schema_version": GUIDELINES_SCHEMA,
        "account_handle": HANDLE,
        "source_path": "docs/examples/drleewarren-content-guidelines.md",
        "sections": sections,
        "tests": {"first15": {"status": "measured", "table": None}},
        "coverage": {
            "sample_n": 62,
            "catalog_n": 262,
            "transcript_yield": 1.0,
            "component_yield": 1.0,
            "note": "seeded from the compiled golden artefact, not a live replay",
        },
    }
    errors = validate_artefact(artefact)
    if errors:
        raise ValueError(f"golden artefact failed schema: {errors}")
    return artefact


def seed_warren_brief(*, store=None, path: Path | None = None, status: str = "confirmed") -> dict[str, Any]:
    store = store or get_store()
    artefact = parse_golden_markdown((path or golden_path()).read_text(encoding="utf-8"))
    profile = store.get("creator_profiles", handle=HANDLE)
    if not profile:
        profile = store.insert(
            "creator_profiles",
            {
                "tiktok_user_id": pending_tiktok_user_id(HANDLE),
                "handle": HANDLE,
                "profile_url": f"https://www.tiktok.com/@{HANDLE}",
                "nickname": "Lee Warren",
                "stage": "scored",
                "lane": "research",
                "geo_country": "US",
                "is_doctor": True,
                "good_fit": True,
                "deep_status": "brief_confirmed" if status == "confirmed" else "brief_draft",
                "review_status": "confirmed",
                "specialty_key": None,
            },
        )
    else:
        store.update(
            "creator_profiles",
            {
                "deep_status": "brief_confirmed" if status == "confirmed" else "brief_draft",
                "review_status": profile.get("review_status") or "confirmed",
            },
            id=profile["id"],
        )
        profile = store.get("creator_profiles", handle=HANDLE) or profile
    row = store.upsert(
        "creator_peer_briefs",
        {
            "creator_profile_id": profile["id"],
            "account_handle": HANDLE,
            "status": status,
            "source": "mcp_session",
            "schema_version": GUIDELINES_SCHEMA,
            "artefact": artefact,
            "coverage": artefact["coverage"],
            "confirmed_by": "seed-warren-brief" if status == "confirmed" else None,
        },
        keys=("account_handle",),
    )
    return {
        "handle": HANDLE,
        "status": status,
        "schema_version": GUIDELINES_SCHEMA,
        "brief_id": row.get("id"),
        "sections": sorted((artefact.get("sections") or {}).keys(), key=int),
    }


def ensure_handle(handle: str) -> str:
    got = normalise_handle(handle)
    if got != HANDLE:
        raise ValueError(f"seed-warren-brief is locked to @{HANDLE}")
    return got
