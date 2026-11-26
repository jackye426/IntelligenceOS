"""Practitioner seed export and shared specialty-map dump."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from gtm_pipeline.creators.paging import fetch_all
from gtm_pipeline.segments.specialty import _CANONICAL_PATTERNS, specialty_to_keys
from gtm_pipeline.shared.supabase_client import get_client, supabase_configured

DEFAULT_SEED_SPECIALTIES = (
    "obstetrics_gynaecology",
    "fertility",
    "menopause",
    "endometriosis",
    "ivf",
    "dermatology",
    "colorectal",
    "general_surgery",
    "gastroenterology",
)

SEED_FIELDS = (
    "slice",
    "source_type",
    "value",
    "priority",
    "practitioner_id",
    "gmc_number",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def export_specialty_map(path: Path | None = None) -> dict[str, Any]:
    payload = {key: list(patterns) for key, patterns in _CANONICAL_PATTERNS.items()}
    dest = path or (
        _repo_root()
        / "marketing-pipeline"
        / "src"
        / "marketing_pipeline"
        / "creators"
        / "specialty_keys.json"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"path": str(dest), "keys": sorted(payload), "count": len(payload)}


def _practitioner_keys(row: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    if row.get("specialty"):
        keys.update(specialty_to_keys(str(row["specialty"])))
    specs = row.get("specialties")
    if isinstance(specs, list):
        for item in specs:
            keys.update(specialty_to_keys(str(item)))
    elif isinstance(specs, str) and specs.strip():
        keys.update(specialty_to_keys(specs))
    return keys


def export_practitioner_seeds(
    *,
    specialties: list[str] | tuple[str, ...] = DEFAULT_SEED_SPECIALTIES,
    limit: int = 1500,
    path: Path | None = None,
    practitioners: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Read integrated_practitioners (not …_with_phin) → CSV for creators seed-import."""
    wanted = {s.strip() for s in specialties if s.strip()}
    if practitioners is None:
        if not supabase_configured():
            return {"count": 0, "reason": "supabase_not_configured", "rows": []}
        client = get_client()
        practitioners = fetch_all(
            lambda: client.table("integrated_practitioners").select(
                "id, name, specialty, specialties, gmc_number"
            ),
            page=1000,
        )
    rows: list[dict[str, str]] = []
    for row in practitioners:
        keys = _practitioner_keys(row)
        if wanted and not (keys & wanted):
            continue
        name = (row.get("name") or "").strip()
        if not name:
            continue
        rows.append(
            {
                "slice": "practitioner",
                "source_type": "user_search",
                "value": name,
                "priority": "80",
                "practitioner_id": str(row.get("id") or ""),
                "gmc_number": str(row.get("gmc_number") or ""),
            }
        )
        if len(rows) >= limit:
            break
    dest = path
    if dest is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(SEED_FIELDS))
            writer.writeheader()
            writer.writerows(rows)
    return {
        "count": len(rows),
        "path": str(dest) if dest else None,
        "specialties": sorted(wanted),
        "rows": rows,
    }
