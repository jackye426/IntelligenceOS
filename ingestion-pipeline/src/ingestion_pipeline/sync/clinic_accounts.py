"""Sync staged clinic accounts to Supabase (P4).

Insert-only: `clinic_accounts` has no metadata column to mark import
provenance, so existing accounts (matched by website URL or normalized name)
are never updated — manual edits in the app always win. New accounts get
draft `clinic_contacts` and a summary embedding (entity_type=clinic_account).
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from ingestion_pipeline.shared.embeddings import upsert_embedding_chunks
from ingestion_pipeline.shared.ingestion_log import finish_run, start_run
from ingestion_pipeline.shared.supabase_client import get_client
from ingestion_pipeline.staging import StagingRecord

logger = logging.getLogger(__name__)

JOB_NAME = "clinic_sales_csv_import"
INSERT_BATCH = 200
PAGE_SIZE = 1000


def _url_key(url: str) -> str:
    """Dedupe key for Doctify profile URLs: normalized host + path.

    Only Doctify URLs are safe to dedupe by URL — they map 1:1 to a clinic.
    Generic websites are shared across sibling clinics (HCA, Phoenix group,
    Cleveland Clinic booking forms), so those rely on name matching only.
    """
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
    except ValueError:
        return ""
    host = parsed.netloc.lower().removeprefix("www.")
    if not host.endswith("doctify.com"):
        return ""
    return host + parsed.path.rstrip("/")


def _norm_name(name: str) -> str:
    return " ".join(name.lower().split())


def _existing_keys() -> tuple[set[str], set[str]]:
    """All (domain, normalized-name) keys already in clinic_accounts."""
    client = get_client()
    domains: set[str] = set()
    names: set[str] = set()
    offset = 0
    while True:
        rows = (
            client.table("clinic_accounts")
            .select("name, website_url")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
            .data
            or []
        )
        for row in rows:
            if row.get("website_url"):
                domains.add(_url_key(row["website_url"]))
            if row.get("name"):
                names.add(_norm_name(row["name"]))
        if len(rows) < PAGE_SIZE:
            return domains, names
        offset += PAGE_SIZE


def sync_clinic_accounts(
    records: list[StagingRecord],
    *,
    dry_run: bool = False,
    skip_embed: bool = False,
) -> dict[str, int]:
    counts = {"rows_seen": len(records), "rows_inserted": 0, "rows_updated": 0,
              "contacts_inserted": 0, "chunks_embedded": 0, "skipped_existing": 0}

    domains, names = _existing_keys()

    new_records: list[StagingRecord] = []
    for record in records:
        domain = _url_key(record.source_url or "")
        if (domain and domain in domains) or _norm_name(record.source_title or "") in names:
            counts["skipped_existing"] += 1
            continue
        # Reserve keys so duplicate CSV rows collapse to one insert.
        if domain:
            domains.add(domain)
        names.add(_norm_name(record.source_title or ""))
        new_records.append(record)

    if dry_run:
        counts["rows_inserted"] = len(new_records)
        logger.info("[dry-run] would insert %d accounts (%d already exist)",
                    len(new_records), counts["skipped_existing"])
        return counts

    client = get_client()
    run_id = start_run(JOB_NAME, {"source": "clinic_sales_results.csv"})
    try:
        for start in range(0, len(new_records), INSERT_BATCH):
            batch = new_records[start : start + INSERT_BATCH]
            payload = [
                {"name": r.source_title, "website_url": r.source_url}
                for r in batch
            ]
            inserted = client.table("clinic_accounts").insert(payload).execute().data or []
            counts["rows_inserted"] += len(inserted)

            # PostgREST returns inserted rows in input order; pair them up.
            # Contacts go in before the slow embedding loop so a mid-batch
            # network failure cannot orphan accounts without their contacts.
            contact_rows: list[dict] = []
            for record, account in zip(batch, inserted):
                for contact in record.metadata.get("contacts", []):
                    contact_rows.append(
                        {
                            "clinic_account_id": account["id"],
                            "name": contact["name"],
                            "role": contact["role"],
                            "email": contact.get("email") or None,
                            "confidence": 0.6,
                            "review_status": "draft",
                        }
                    )
            if contact_rows:
                client.table("clinic_contacts").insert(contact_rows).execute()
                counts["contacts_inserted"] += len(contact_rows)

            if not skip_embed:
                for record, account in zip(batch, inserted):
                    counts["chunks_embedded"] += upsert_embedding_chunks(
                        entity_type="clinic_account",
                        entity_id=account["id"],
                        text=record.embed_text,
                        source_table="clinic_accounts",
                        source_title=record.source_title,
                        source_url=record.source_url,
                        sensitivity=record.sensitivity,
                        metadata={
                            k: v
                            for k, v in record.metadata.items()
                            if k in ("import_source", "location", "specialty_tags")
                        },
                        # Freshly inserted account: no prior chunks to diff against.
                        skip_unchanged=False,
                    )

            logger.info("Inserted %d/%d accounts", counts["rows_inserted"], len(new_records))

        finish_run(run_id, "success", counts)
    except Exception as exc:
        try:
            finish_run(run_id, "failed", counts, error=str(exc)[:500])
        except Exception:
            logger.exception("Could not record failed run %s", run_id)
        raise

    return counts
