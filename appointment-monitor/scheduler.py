"""3×/day Spire scrape scheduler (Europe/London).

Usage:
  python scheduler.py
  python scheduler.py --test-interval 2
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: E402
from apscheduler.triggers.cron import CronTrigger  # noqa: E402

from spire_monitor.config import LOG_LEVEL, SCRAPE_TIMES_LONDON  # noqa: E402

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("scheduler")

_TZ = ZoneInfo("Europe/London")


def _run_scrape() -> None:
    from run_once import run

    logger.info(
        "Scheduled scrape at %s",
        datetime.now(_TZ).strftime("%Y-%m-%d %H:%M %Z"),
    )
    try:
        result = run()
        logger.info("Scheduled scrape done: %s", result.get("status"))
    except Exception:
        logger.exception("Scheduled scrape failed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test-interval",
        type=int,
        metavar="MINUTES",
        help="Run every N minutes instead of 3×/day",
    )
    args = parser.parse_args()

    scheduler = BlockingScheduler(timezone="Europe/London")

    if args.test_interval:
        logger.info("TEST MODE: every %d minute(s)", args.test_interval)
        scheduler.add_job(
            _run_scrape,
            "interval",
            minutes=args.test_interval,
            id="spire_test",
            replace_existing=True,
        )
    else:
        for t in SCRAPE_TIMES_LONDON:
            hour, minute = map(int, t.split(":"))
            scheduler.add_job(
                _run_scrape,
                CronTrigger(hour=hour, minute=minute, timezone="Europe/London"),
                id=f"spire_{t.replace(':', '')}",
                replace_existing=True,
            )
            logger.info("Scheduled scrape at %s Europe/London", t)

    def shutdown(_signum, _frame):
        logger.info("Shutting down")
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    import os

    if os.getenv("RUN_ON_START", "").lower() in {"1", "true", "yes"}:
        logger.info("RUN_ON_START — scraping once now")
        _run_scrape()

    logger.info("Spire appointment-monitor scheduler ready")
    scheduler.start()


if __name__ == "__main__":
    main()
