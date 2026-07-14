"""Sync Clinic sales scoped CSV rows into gtm_clinic_intelligence."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

from gtm_pipeline.scoring import classify_visible_clinic_size, compute_founder_score
from gtm_pipeline.shared.address import normalise_postcode
from gtm_pipeline.shared.provenance import evidence_item, make_provenance
from gtm_pipeline.sync.clinic_intelligence import (
    find_or_create_clinic_account,
    upsert_clinic_intelligence,
    upsert_clinic_people,
)

logger = logging.getLogger(__name__)

_CONF_MAP = {
    "exact": 1.0,
    "fuzzy": 0.75,
    "name_website": 0.92,
    "website": 0.85,
    "name_only": 0.80,
    "geo": 0.88,
}


def _postcode_from_location(location: str) -> str:
    m = re.search(r"\b([A-Z]{1,2}[0-9][0-9A-Z]?\s*[0-9][A-Z]{2})\b", (location or "").upper())
    return normalise_postcode(m.group(1)) if m else ""


def _specialties(raw: str) -> list[str]:
    if not raw or not str(raw).strip():
        return []
    parts = re.split(r"[|;,]", str(raw))
    return [p.strip() for p in parts if p.strip()]


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def row_to_intelligence_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Map a Clinic sales agent CSV row → gtm_clinic_intelligence fields."""
    specialist_count = _int_or_none(row.get("specialist_count"))
    size = classify_visible_clinic_size(specialist_count)
    rm = (row.get("cqc_registered_manager") or "").strip()
    ni = (row.get("cqc_nominated_individual") or "").strip()
    cqc_id = (row.get("cqc_location_id") or "").strip()
    if cqc_id == "NOT_FOUND":
        cqc_id = ""

    conf_label = (row.get("cqc_match_confidence") or "").strip().lower()
    conf_num = _CONF_MAP.get(conf_label)

    score, structure = compute_founder_score(
        leadership=None,
        visible_clinic_size=size,
        has_cqc_rm=bool(rm or ni),
        specialist_count=specialist_count,
    )

    doctify_url = (row.get("doctify_profile_url") or "").strip()
    clinic_name = (row.get("clinic_name") or "").strip()
    website = (row.get("website_url") or "").strip()
    location = (row.get("location") or "").strip()

    evidence = [
        evidence_item(
            kind="scoped_csv_row",
            value={
                "status": row.get("status"),
                "cqc_match_label": conf_label,
                "specialist_count": specialist_count,
            },
            source="clinic_sales_scoped_csv",
            source_url=doctify_url or None,
        )
    ]
    provenance = make_provenance(
        source="clinic_sales_scoped_csv",
        source_url=doctify_url or None,
        lane="scoped_csv_sync",
    )

    return {
        "doctify_url": doctify_url or None,
        "clinic_name": clinic_name or None,
        "website_url": website or None,
        "email": (row.get("contact_email") or "").strip() or None,
        "phone": (row.get("phone") or "").strip() or None,
        "address": location or None,
        "postcode": _postcode_from_location(location) or None,
        "bio": (row.get("doctify_about") or "").strip() or None,
        "specialties": _specialties(row.get("specialty_tags") or ""),
        "listed_specialist_count": specialist_count,
        "visible_clinic_size": size,
        "cqc_location_id": cqc_id or None,
        "cqc_location_url": f"https://www.cqc.org.uk/location/{cqc_id}" if cqc_id else None,
        "cqc_registered_manager": rm or None,
        "cqc_nominated_individual": ni or None,
        "cqc_match_confidence": conf_num,
        "cqc_match_reasons": [{"method": conf_label}] if conf_label else [],
        "founder_score": score,
        "structure": structure,
        "evidence": evidence,
        "provenance": provenance,
    }


def sync_scoped_csv(
    path: Path | str,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    skip_pre_filtered: bool = True,
    attach_cqc_people: bool = True,
) -> dict[str, Any]:
    """Upsert scoped discovery CSV into Supabase gtm_* tables."""
    path = Path(path)
    df = pd.read_csv(path, dtype=str).fillna("")
    if skip_pre_filtered and "status" in df.columns:
        df = df[df["status"] != "pre_filtered"]
    if limit is not None:
        df = df.head(limit)

    stats = {
        "rows": len(df),
        "upserted": 0,
        "people": 0,
        "skipped": 0,
        "dry_run": dry_run,
        "errors": [],
    }

    for _, series in df.iterrows():
        row = series.to_dict()
        if not (row.get("doctify_profile_url") or row.get("clinic_name")):
            stats["skipped"] += 1
            continue
        try:
            payload = row_to_intelligence_payload(row)
            account_id = find_or_create_clinic_account(
                name=payload.get("clinic_name") or "",
                doctify_url=payload.get("doctify_url") or "",
                website_url=payload.get("website_url") or "",
                dry_run=dry_run,
            )
            if account_id:
                payload["clinic_account_id"] = account_id
            result = upsert_clinic_intelligence(payload, dry_run=dry_run)
            stats["upserted"] += 1

            if attach_cqc_people:
                intel_id = result.get("id")
                people_payload: list[dict[str, Any]] = []
                for role, field in (
                    ("nominated_individual", "cqc_nominated_individual"),
                    ("registered_manager", "cqc_registered_manager"),
                ):
                    name = (payload.get(field) or "").strip()
                    if not name:
                        continue
                    if (
                        role == "registered_manager"
                        and name == (payload.get("cqc_nominated_individual") or "").strip()
                    ):
                        continue
                    people_payload.append(
                        {
                            "full_name": name,
                            "role": role,
                            "priority": 90 if role == "nominated_individual" else 80,
                            "reasons": [{"source": "cqc", "field": field}],
                            "evidence": [
                                evidence_item(
                                    kind="cqc_role",
                                    value={"role": role, "name": name},
                                    source="cqc",
                                )
                            ],
                            "provenance": make_provenance(
                                source="cqc_scoped_csv", lane="scoped_csv_sync"
                            ),
                        }
                    )
                if people_payload:
                    n = upsert_clinic_people(
                        intel_id or "",
                        people_payload,
                        clinic_account_id=account_id,
                        dry_run=dry_run or not intel_id,
                    )
                    stats["people"] += n
        except Exception as exc:  # noqa: BLE001 — continue batch
            logger.exception("scoped sync failed for %s", row.get("clinic_name"))
            stats["errors"].append({"clinic": row.get("clinic_name"), "error": str(exc)})

    return stats
