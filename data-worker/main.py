"""DocMap data worker — scheduled ingestion jobs.

Run locally:
  cd data-worker
  pip install -r requirements.txt
  python main.py

Production (Railway):
  Set SKIP_CONTENT_TRACKER=true and SKIP_HCA=true for TikTok-only cron.
  Set MARKETING_DATA_DIR to a mounted volume path for persistent transcripts.
  Transcription runs on worker when SKIP_TRANSCRIBE is not true.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from common import config  # noqa: E402

os.environ.setdefault("MARKETING_DATA_DIR", config.MARKETING_DATA_DIR)
os.environ.setdefault("WHISPER_MODEL", config.WHISPER_MODEL)
# Cache the Whisper model on the persistent volume so it is not re-downloaded
# from HuggingFace on every cold start / restart.
os.environ.setdefault("HF_HOME", str(Path(config.MARKETING_DATA_DIR) / ".hf_cache"))

from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: E402
from apscheduler.triggers.cron import CronTrigger  # noqa: E402

import marketing_pipeline.bootstrap as _bootstrap_mod  # noqa: E402
from marketing_pipeline.bootstrap import ensure_pipeline_data  # noqa: E402
from marketing_pipeline.tiktok.orchestrator import (  # noqa: E402
    run_export,
    run_ocr_batch,
    run_refresh,
    run_refresh_comments,
    run_sync_playbooks_cmd,
    run_sync_supabase,
)
from marketing_pipeline.tiktok.stages.fetch_catalog import fetch_catalog  # noqa: E402
from marketing_pipeline.tiktok.stages.refresh_videos import refresh_videos  # noqa: E402
from marketing_pipeline.tiktok.stages.write_master_transcripts import (  # noqa: E402
    write_master_transcripts,
)

from jobs.content_tracker import run_content_tracker  # noqa: E402
from jobs.hca_sqlite import run_hca_migration  # noqa: E402

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


def _transcribe_new_videos() -> dict:
    """Fetch catalog and transcribe any videos missing COMPLETE transcripts."""
    fetch_catalog()
    videos = refresh_videos(
        skip_transcribe=False,
        whisper_model=config.WHISPER_MODEL,
        download_if_missing=True,
    )
    master = write_master_transcripts(refresh_metrics=False)
    return {"videos": videos, "master": master}


def _run_tiktok_pipeline(*, full_refresh: bool = False, include_ocr: bool = False) -> dict:
    """Export + sync; refresh comments; transcribe new videos on worker."""
    result: dict = {}

    if full_refresh:
        result["refresh"] = run_refresh(
            skip_transcribe=config.SKIP_TRANSCRIBE,
            skip_ocr=not include_ocr,
        )
    else:
        try:
            result["comments"] = run_refresh_comments()
        except Exception as exc:
            logger.warning("refresh-comments failed: %s", exc)

        if not config.SKIP_TRANSCRIBE:
            try:
                result["transcribe"] = _transcribe_new_videos()
            except Exception as exc:
                logger.exception("transcribe-new-videos failed: %s", exc)

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
    logger.info("marketing_pipeline.bootstrap at %s", _bootstrap_mod.__file__)
    bootstrap = ensure_pipeline_data()
    logger.info("Pipeline data: %s", bootstrap)
    if bootstrap.get("error"):
        logger.warning(
            "Pipeline seed failed — cron jobs may fail until MARKETING_DATA_DIR is populated"
        )

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

    if config.SKIP_TRANSCRIBE:
        logger.info("SKIP_TRANSCRIBE=true — worker will not run Whisper")
    else:
        logger.info(
            "Transcription enabled on worker (model=%s, data=%s)",
            config.WHISPER_MODEL,
            config.MARKETING_DATA_DIR,
        )

    def shutdown(_signum, _frame):
        logger.info("Shutting down scheduler")
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("Data worker ready")

    if os.getenv("RUN_ON_START", "").lower() in {"1", "true", "yes"}:
        logger.info("RUN_ON_START enabled — running tiktok pipeline once now")
        _safe("tiktok_marketing_on_start", lambda: _run_tiktok_pipeline())()

    scheduler.start()


if __name__ == "__main__":
    main()
