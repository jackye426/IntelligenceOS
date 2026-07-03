"""DocMap data worker — scheduled ingestion jobs.

Run locally:
  cd data-worker
  pip install -r requirements.txt
  python main.py

Production (Railway):
  Set SKIP_CONTENT_TRACKER=true and SKIP_HCA=true for TikTok-only cron.
"""

from __future__ import annotations

import logging
import signal
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from marketing_pipeline.tiktok.orchestrator import (
    run_export,
    run_ocr_batch,
    run_refresh,
    run_refresh_comments,
    run_sync_playbooks_cmd,
    run_sync_supabase,
)

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from jobs.content_tracker import run_content_tracker  # noqa: E402
from jobs.hca_sqlite import run_hca_migration  # noqa: E402
from common import config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("data-worker")


def _safe(job_name: str, fn):
    def wrapper():
        logger.info("Starting job: %s", job_name)
        try:
            result = fn()
            logger.info("Finished job %s: %s", job_name, result)
        except FileNotFoundError as exc:
            logger.warning("Skipped job %s: %s", job_name, exc)
        except Exception:
            logger.exception("Job %s failed", job_name)

    return wrapper


def _run_tiktok_pipeline(*, full_refresh: bool = False, include_ocr: bool = False) -> dict:
    """Export + sync; optionally refresh comments or full catalog refresh."""
    result: dict = {}

    if full_refresh:
        result["refresh"] = run_refresh(
            skip_transcribe=True,
            skip_ocr=not include_ocr,
        )
    else:
        try:
            result["comments"] = run_refresh_comments()
        except Exception as exc:
            logger.warning("refresh-comments failed: %s", exc)

    result["export"] = run_export()
    result["sync"] = run_sync_supabase()
    try:
        result["playbooks"] = run_sync_playbooks_cmd()
    except Exception as exc:
        logger.warning("sync-playbooks failed: %s", exc)
        result["playbooks"] = {"error": str(exc)}

    if include_ocr and not full_refresh:
        try:
            result["ocr"] = run_ocr_batch()
        except Exception as exc:
            logger.warning("ocr-hooks failed: %s", exc)
            result["ocr"] = {"error": str(exc)}

    return result


def main() -> None:
    scheduler = BlockingScheduler(timezone="UTC")

    if not config.SKIP_CONTENT_TRACKER:
        scheduler.add_job(
            _safe("content_tracker", run_content_tracker),
            CronTrigger(hour=3, minute=0),
            id="content_tracker",
            replace_existing=True,
        )
    else:
        logger.info("SKIP_CONTENT_TRACKER=true — content tracker job disabled")

    scheduler.add_job(
        _safe("tiktok_marketing", lambda: _run_tiktok_pipeline()),
        CronTrigger(hour=3, minute=30),
        id="tiktok_marketing",
        replace_existing=True,
    )

    scheduler.add_job(
        _safe(
            "tiktok_weekly",
            lambda: _run_tiktok_pipeline(full_refresh=True, include_ocr=True),
        ),
        CronTrigger(day_of_week="sun", hour=2, minute=0),
        id="tiktok_weekly",
        replace_existing=True,
    )

    if not config.SKIP_HCA:
        scheduler.add_job(
            _safe("hca_sqlite_migration", run_hca_migration),
            CronTrigger(hour=4, minute=0),
            id="hca_sqlite_migration",
            replace_existing=True,
        )
    else:
        logger.info("SKIP_HCA=true — HCA migration job disabled")

    def shutdown(_signum, _frame):
        logger.info("Shutting down scheduler")
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("Data worker ready")
    scheduler.start()


if __name__ == "__main__":
    main()
