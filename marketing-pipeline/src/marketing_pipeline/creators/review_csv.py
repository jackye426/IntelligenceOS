"""CSV round-trip for human review of customer-lane creators."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from marketing_pipeline.creators.paths import normalise_handle
from marketing_pipeline.creators.store import get_store

REVIEW_FIELDS = [
    "handle",
    "lane",
    "review_status",
    "review_lane_override",
    "do_not_contact",
    "review_note",
    "customer_score",
    "specialty_key",
    "geo_country",
    "gmc_number_in_bio",
    "bio_email",
    "best_link_method",
    "best_link_status",
]


def review_export(*, path: Path, store=None) -> dict[str, Any]:
    store = store or get_store()
    profiles = [
        p
        for p in store.list("creator_profiles")
        if p.get("lane") in {"customer", "both", "pending_review"}
    ]
    links = store.list("creator_links")
    best: dict[str, dict[str, Any]] = {}
    for link in links:
        pid = link.get("creator_profile_id")
        prev = best.get(pid)
        if prev is None or float(link.get("confidence") or 0) > float(prev.get("confidence") or 0):
            best[pid] = link
    rows = []
    for profile in profiles:
        link = best.get(profile["id"]) or {}
        emails = profile.get("bio_emails") or []
        rows.append(
            {
                "handle": profile.get("handle"),
                "lane": profile.get("lane"),
                "review_status": profile.get("review_status") or "pending",
                "review_lane_override": profile.get("review_lane_override") or "",
                "do_not_contact": profile.get("do_not_contact") or False,
                "review_note": profile.get("review_note") or "",
                "customer_score": profile.get("customer_score"),
                "specialty_key": profile.get("specialty_key"),
                "geo_country": profile.get("geo_country"),
                "gmc_number_in_bio": profile.get("gmc_number_in_bio") or "",
                "bio_email": emails[0] if emails else "",
                "best_link_method": link.get("method") or "",
                "best_link_status": link.get("status") or "",
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return {"path": str(path), "rows": len(rows)}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def review_import(*, path: Path, store=None) -> dict[str, Any]:
    store = store or get_store()
    updated = 0
    skipped = 0
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            handle = normalise_handle(row.get("handle") or "")
            if not handle:
                skipped += 1
                continue
            profile = store.get("creator_profiles", handle=handle)
            if not profile:
                skipped += 1
                continue
            patch = {
                "review_status": (row.get("review_status") or profile.get("review_status") or "pending").strip(),
                "review_lane_override": (row.get("review_lane_override") or "").strip() or None,
                "do_not_contact": _as_bool(row.get("do_not_contact")),
                "review_note": (row.get("review_note") or "").strip() or None,
            }
            store.update("creator_profiles", patch, id=profile["id"])
            updated += 1
    return {"path": str(path), "updated": updated, "skipped": skipped}
