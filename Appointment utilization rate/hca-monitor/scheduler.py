"""
3×/day schedule runner. Scrapes at 07:00, 13:00, 19:00 Europe/London.

Usage:
    python scheduler.py               # run on the configured cadence
    python scheduler.py --test-interval 2  # run every 2 minutes for quick testing
"""

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import schedule

from config.settings import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path("logs") / "scheduler.log"),
    ],
)
logger = logging.getLogger(__name__)

_TZ_LONDON = ZoneInfo("Europe/London")


def run_scrape() -> None:
    """Synchronous wrapper called by the schedule library."""
    from run_once import main  # imported here so schedule can reload on file change
    logger.info("Scheduled scrape triggered at %s", datetime.now(_TZ_LONDON).strftime("%Y-%m-%d %H:%M %Z"))
    asyncio.run(main())
    logger.info("Scheduled scrape complete")


def setup_schedule(test_interval_minutes: int | None = None) -> None:
    if test_interval_minutes:
        logger.info("TEST MODE: running every %d minute(s)", test_interval_minutes)
        schedule.every(test_interval_minutes).minutes.do(run_scrape)
    else:
        for t in settings.scrape_times:
            schedule.every().day.at(t, "Europe/London").do(run_scrape)
            logger.info("Scheduled scrape at %s Europe/London", t)


def main_loop(test_interval_minutes: int | None = None) -> None:
    setup_schedule(test_interval_minutes)
    logger.info("Scheduler running. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test-interval",
        type=int,
        metavar="MINUTES",
        help="Run every N minutes instead of the configured 3x/day cadence",
    )
    args = parser.parse_args()
    try:
        main_loop(test_interval_minutes=args.test_interval)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
