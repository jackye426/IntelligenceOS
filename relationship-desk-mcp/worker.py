"""Relationship Desk worker for inbox follow-up detection.

Production:
  python worker.py
"""

from __future__ import annotations

import logging
import os
import signal
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from tools import followup_candidates, sync_replies  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("relationship-desk-worker")


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "true" if default else "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _safe(job_name: str, fn):
    def wrapper():
        logger.info("Starting job: %s", job_name)
        try:
            result = fn()
            logger.info("Finished job %s: %s", job_name, result)
        except Exception:
            logger.exception("Job %s failed", job_name)

    return wrapper


def _sync_replies() -> dict:
    return sync_replies.run(limit=_int_env("RELATIONSHIP_WORKER_SYNC_LIMIT", 100))


def _scan_inbox() -> dict:
    return followup_candidates.scan_inbox(
        hours_back=_int_env("RELATIONSHIP_WORKER_SCAN_HOURS_BACK", 96),
        max_results=_int_env("RELATIONSHIP_WORKER_SCAN_MAX_RESULTS", 50),
        auto_convert_high_confidence=_bool_env("RELATIONSHIP_WORKER_AUTO_CONVERT", False),
        min_confidence=float(os.getenv("RELATIONSHIP_WORKER_MIN_CONFIDENCE", "0.65")),
    )


def main() -> None:
    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(
        _safe("sync_replies", _sync_replies),
        CronTrigger(minute="*/30"),
        id="sync_replies",
        replace_existing=True,
    )
    scheduler.add_job(
        _safe("scan_inbox_for_followups", _scan_inbox),
        CronTrigger(minute=10, hour="*/2"),
        id="scan_inbox_for_followups",
        replace_existing=True,
    )

    def shutdown(_signum, _frame):
        logger.info("Shutting down scheduler")
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    if _bool_env("RELATIONSHIP_WORKER_RUN_ON_START", False):
        _safe("sync_replies_on_start", _sync_replies)()
        _safe("scan_inbox_for_followups_on_start", _scan_inbox)()

    logger.info("Relationship Desk worker ready")
    scheduler.start()


if __name__ == "__main__":
    main()
