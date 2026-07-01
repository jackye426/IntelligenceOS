"""
Single end-to-end scrape run entry point.

Usage:
    python run_once.py
    python run_once.py --dump-network    # write network log for API investigation
    python run_once.py --trace           # write Playwright trace for debugging

Routing logic:
    Consultants with stored GUIDs (booking_guids table) -> direct API scraper
      - One lightweight T&C page load per consultant
      - All locations x appt types fetched via direct HTTP
    Consultants with no stored GUIDs (new / never scraped) -> full browser flow
      - booking_navigator.py drives the multi-step UI
      - GUIDs are stored via source_url on AppointmentSlot rows
      - Picked up by guid_store.populate_from_slots() on the next run
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from config.settings import settings
from db.engine import get_session
from db.migrations import create_all
from scraper.browser import create_browser_context
from scraper.booking_navigator import scrape_consultant
from scraper.direct_api_scraper import scrape_consultant_direct
from scraper.profile_extractor import extract_profile
from storage.guid_store import get_guids_for_consultant, populate_from_slots
from storage.scrape_run import close_scrape_run, close_scrape_run_on_error, open_scrape_run
from storage.slot_lifecycle import persist_consultant, upsert_slots

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path("logs") / f"scrape_{datetime.now().strftime('%Y%m%d')}.log"),
    ],
)
logger = logging.getLogger(__name__)


async def main(dump_network: bool = False, trace: bool = False) -> None:
    create_all()
    session = get_session()

    # Seed booking_guids from any source_url values already in appointment_slots
    new_guids = populate_from_slots(session)
    if new_guids:
        logger.info("Seeded %d new GUID entries from existing slot data", new_guids)

    run = open_scrape_run(session)
    total_slots = 0
    direct_count = 0
    browser_count = 0

    try:
        async with create_browser_context() as (browser, context):
            if trace:
                await context.tracing.start(screenshots=True, snapshots=True)

            terms_state: dict = {}

            for consultant_cfg in settings.consultants:
                profile_url = consultant_cfg["profile_url"]
                logger.info("Processing consultant: %s", consultant_cfg["name"])

                # Extract profile (opens a temporary page)
                profile_page = await context.new_page()
                try:
                    profile = await extract_profile(profile_page, profile_url)
                finally:
                    await profile_page.close()

                # Persist consultant + locations, get DB ID
                consultant_id = persist_consultant(session, profile)
                logger.info(
                    "Consultant '%s' (ID=%d) with %d location(s)",
                    profile.name, consultant_id, len(profile.locations),
                )

                # Route: direct API if GUIDs are known, otherwise full browser flow
                guids = get_guids_for_consultant(session, consultant_id)
                if guids:
                    logger.info(
                        "Direct API path: %d location/funding combos known for '%s'",
                        len(guids), profile.name,
                    )
                    slots = await scrape_consultant_direct(
                        context=context,
                        consultant_id=consultant_id,
                        consultant_name=profile.name,
                        profile_url=profile.profile_url,
                        guids=guids,
                    )
                    direct_count += 1
                else:
                    logger.info(
                        "Browser flow path: no stored GUIDs for '%s' — running full navigation",
                        profile.name,
                    )
                    slots = await scrape_consultant(
                        context=context,
                        profile=profile,
                        consultant_id=consultant_id,
                        terms_state=terms_state,
                    )
                    browser_count += 1
                    # Pick up GUIDs discovered during this browser run immediately,
                    # so subsequent consultants in the same session can also benefit
                    # if they share locations (unlikely but safe).
                    populate_from_slots(session)

                # Group by (location, funding_route) and upsert
                collection_ts = datetime.now(timezone.utc)
                groups: dict[tuple, list] = {}
                for s in slots:
                    key = (s.location_name, s.funding_route)
                    groups.setdefault(key, []).append(s)

                for (loc, fund), group_slots in groups.items():
                    upsert_slots(
                        session=session,
                        slots=group_slots,
                        scrape_run_id=run.scrape_run_id,
                        collection_ts=collection_ts,
                    )
                    unique_times = len(set(s.slot_datetime for s in group_slots))
                    total_slots += unique_times

                if dump_network:
                    logger.info("Network log path (reference only): logs/network_*.json")

            if trace:
                trace_path = f"logs/trace_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.zip"
                await context.tracing.stop(path=trace_path)
                logger.info("Playwright trace written to: %s", trace_path)

        close_scrape_run(
            session, run,
            status="completed",
            notes=(
                f"Total slots: {total_slots} | "
                f"Direct API: {direct_count} consultant(s) | "
                f"Browser flow: {browser_count} consultant(s)"
            ),
        )
        logger.info(
            "Scrape run complete. slots=%d  direct=%d  browser=%d",
            total_slots, direct_count, browser_count,
        )

    except Exception:
        logger.exception("Fatal error in scrape run")
        close_scrape_run_on_error(session, run)
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump-network", action="store_true", help="Dump captured network endpoints to JSON")
    parser.add_argument("--trace", action="store_true", help="Write Playwright trace file")
    args = parser.parse_args()
    asyncio.run(main(dump_network=args.dump_network, trace=args.trace))
