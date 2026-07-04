"""Parse Clinic sales agent results CSV into staging envelopes (P4).

Column mapping (see docs/DATA_INGESTION_PLANS.md P4):
  clinic_name          -> clinic_accounts.name
  website_url          -> clinic_accounts.website_url (falls back to
                          doctify_profile_url — column is NOT NULL and the
                          Doctify URL is present on every row)
  status=pre_filtered  -> skipped by default (hospitals/NHS excluded upstream)
  cqc_registered_manager / contact_email -> draft clinic_contacts
  location, specialty_tags, doctify_about, review counts -> embed summary

`source_id` is the Doctify profile URL: stable, unique, present on all rows.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ingestion_pipeline.shared.hashing import content_hash
from ingestion_pipeline.staging import StagingRecord

LANE = "clinic_accounts"


def _summary(row: dict[str, str]) -> str:
    """Structured paragraph embedded as entity_type=clinic_account."""
    parts = [f"{row['clinic_name']}."]
    if row.get("location"):
        parts.append(f"Location: {row['location']}.")
    if row.get("specialty_tags"):
        parts.append(f"Specialties: {row['specialty_tags']}.")
    if row.get("specialist_count"):
        parts.append(f"{row['specialist_count']} specialists listed on Doctify.")
    if row.get("review_count"):
        parts.append(f"{row['review_count']} Doctify reviews.")
    if row.get("cqc_registered_manager"):
        parts.append(f"CQC registered manager: {row['cqc_registered_manager']}.")
    if row.get("doctify_about"):
        parts.append(row["doctify_about"][:1200])
    return " ".join(parts)


def _contacts(row: dict[str, str]) -> list[dict[str, str]]:
    contacts: list[dict[str, str]] = []
    if row.get("cqc_registered_manager"):
        contacts.append(
            {
                "name": row["cqc_registered_manager"],
                "role": "Registered Manager (CQC)",
                "email": "",
            }
        )
    if row.get("contact_email"):
        contacts.append(
            {
                "name": "Reception / general enquiries",
                "role": "General enquiries",
                "email": row["contact_email"],
            }
        )
    return contacts


def parse_clinic_csv(
    csv_path: Path,
    *,
    include_filtered: bool = False,
    limit: int | None = None,
) -> list[StagingRecord]:
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    records: list[StagingRecord] = []
    for row in rows:
        if not include_filtered and row.get("status") == "pre_filtered":
            continue

        name = (row.get("clinic_name") or "").strip()
        doctify_url = (row.get("doctify_profile_url") or "").strip()
        if not name or not doctify_url:
            continue

        website = (row.get("website_url") or "").strip() or doctify_url
        summary = _summary(row)
        records.append(
            StagingRecord(
                lane=LANE,
                source_system="clinic_sales_csv",
                source_id=doctify_url,
                content_hash=content_hash(summary),
                sensitivity="internal",
                source_title=name,
                source_url=website,
                raw_text=summary,
                embed_text=summary,
                metadata={
                    "import_source": "clinic_sales_csv",
                    "location": row.get("location") or "",
                    "specialty_tags": row.get("specialty_tags") or "",
                    "doctify_profile_url": doctify_url,
                    "phone": row.get("phone") or "",
                    "csv_status": row.get("status") or "",
                    "contacts": _contacts(row),
                },
            )
        )
        if limit is not None and len(records) >= limit:
            break

    return records
