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
import subprocess
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

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
    """Export + sync; optionally refresh comments or full legacy refresh."""
    repo = config.REPO_ROOT
    if full_refresh:
        refresh_cmd = [
            sys.executable,
            "-m",
            "marketing_pipeline",
            "tiktok",
            "refresh",
            "--skip-transcribe",
        ]
        if not include_ocr:
            refresh_cmd.append("--skip-ocr")
        refresh = subprocess.run(
            refresh_cmd,
            cwd=str(repo),
            check=False,
            capture_output=True,
            text=True,
        )
        if refresh.returncode != 0:
            raise RuntimeError(f"tiktok refresh failed: {refresh.stderr or refresh.stdout}")
    else:
        comments = subprocess.run(
            [sys.executable, "-m", "marketing_pipeline", "tiktok", "refresh-comments"],
            cwd=str(repo),
            check=False,
            capture_output=True,
            text=True,
        )
        if comments.returncode != 0:
            logger.warning("refresh-comments failed: %s", comments.stderr or comments.stdout)

    export = subprocess.run(
        [sys.executable, "-m", "marketing_pipeline", "tiktok", "export"],
        cwd=str(repo),
        check=False,
        capture_output=True,
        text=True,
    )
    if export.returncode != 0:
        raise RuntimeError(f"tiktok export failed: {export.stderr or export.stdout}")

    sync = subprocess.run(
        [sys.executable, "-m", "marketing_pipeline", "tiktok", "sync-supabase"],
        cwd=str(repo),
        check=False,
        capture_output=True,
        text=True,
    )
    if sync.returncode != 0:
        raise RuntimeError(f"tiktok sync failed: {sync.stderr or sync.stdout}")

    playbooks = subprocess.run(
        [sys.executable, "-m", "marketing_pipeline", "tiktok", "sync-playbooks"],
        cwd=str(repo),
        check=False,
        capture_output=True,
        text=True,
    )

    ocr_result = ""
    if include_ocr and not full_refresh:
        ocr = subprocess.run(
            [sys.executable, "-m", "marketing_pipeline", "tiktok", "ocr-hooks"],
            cwd=str(repo),
            check=False,
            capture_output=True,
            text=True,
        )
        ocr_result = ocr.stdout.strip() if ocr.returncode == 0 else ocr.stderr

    return {
        "export": export.stdout.strip(),
        "sync": sync.stdout.strip(),
        "playbooks": playbooks.stdout.strip() if playbooks.returncode == 0 else playbooks.stderr,
        "ocr": ocr_result,
    }


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
