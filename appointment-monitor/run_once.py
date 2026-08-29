"""Single scrape run: all roster consultants → Supabase."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from spire_monitor.api_client import (  # noqa: E402
    SpireApiError,
    resolve_consultant_id,
    scrape_consultant_slots,
)
from spire_monitor.config import (  # noqa: E402
    DRY_RUN,
    LOG_LEVEL,
    MAX_LOOKAHEAD_MONTHS,
    load_consultants,
)
from spire_monitor.store import (  # noqa: E402
    finish_ingestion_run,
    start_ingestion_run,
    upsert_consultant_slots,
)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("run_once")


def run(*, dry_run: bool | None = None, lookahead_months: int | None = None) -> dict:
    dry = DRY_RUN if dry_run is None else dry_run
    months = lookahead_months or MAX_LOOKAHEAD_MONTHS
    consultants = load_consultants()
    logger.info(
        "Spire scrape starting: %d consultant(s), lookahead=%d months, dry_run=%s",
        len(consultants),
        months,
        dry,
    )

    run_id = None if dry else start_ingestion_run(
        {"consultants": [c.consultant_id for c in consultants], "lookahead_months": months}
    )

    totals = {
        "rows_seen": 0,
        "rows_inserted": 0,
        "rows_updated": 0,
        "disappeared": 0,
        "expired": 0,
        "consultants_ok": 0,
        "consultants_failed": 0,
        "consultants_skipped": 0,
    }
    errors: list[str] = []
    partial = False

    for c in consultants:
        logger.info("Processing %s (%s)", c.name, c.consultant_id)
        try:
            cid = resolve_consultant_id(c.profile_url, c.consultant_id)
            slots, stats = scrape_consultant_slots(cid, lookahead_months=months)
            if stats.get("partial"):
                partial = True
            if stats["locations"] == 0:
                logger.warning("No online locations for %s — skipping", c.name)
                totals["consultants_skipped"] += 1
                continue
            logger.info(
                "  scraped %d slots across %d location(s), %d day(s)",
                stats["slots"],
                stats["locations"],
                stats["days"],
            )
            if dry:
                sample = [
                    f"{s['starts_at']} @ {s['location_name']}" for s in slots[:5]
                ]
                logger.info("  dry-run sample: %s", sample)
                totals["rows_seen"] += len(slots)
                totals["consultants_ok"] += 1
                continue

            counts = upsert_consultant_slots(
                consultant_id=cid,
                consultant_name=c.name,
                profile_url=c.profile_url,
                slots=slots,
            )
            for k in ("rows_seen", "rows_inserted", "rows_updated", "disappeared", "expired"):
                totals[k] = totals.get(k, 0) + counts.get(k, 0)
            totals["consultants_ok"] += 1
        except SpireApiError as e:
            partial = True
            totals["consultants_failed"] += 1
            msg = f"{c.name}: {e}"
            errors.append(msg)
            logger.error("Consultant failed (continuing): %s", msg)
        except Exception as e:
            partial = True
            totals["consultants_failed"] += 1
            msg = f"{c.name}: {e}"
            errors.append(msg)
            logger.exception("Unexpected failure for %s", c.name)

    if dry:
        status = "dry_run"
    elif totals["consultants_failed"] and totals["consultants_ok"] == 0:
        status = "failed"
    elif partial or totals["consultants_failed"] or totals["consultants_skipped"]:
        status = "partial"
    else:
        status = "success"

    err_text = "; ".join(errors) if errors else None
    if not dry:
        finish_ingestion_run(run_id, status, totals, error=err_text)

    logger.info("Scrape finished status=%s totals=%s", status, totals)
    return {"status": status, "totals": totals, "errors": errors, "run_id": run_id}


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Spire appointment slots once")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch slots but do not write to Supabase",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=None,
        help="Lookahead months (default from SPIRE_LOOKAHEAD_MONTHS or 3)",
    )
    args = parser.parse_args()
    result = run(dry_run=args.dry_run, lookahead_months=args.months)
    if result["status"] == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
