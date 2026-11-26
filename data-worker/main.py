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
from threading import Lock
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from common import config  # noqa: E402

os.environ.setdefault("MARKETING_DATA_DIR", config.MARKETING_DATA_DIR)
os.environ.setdefault("MARKETING_INSTAGRAM_DATA_DIR", config.MARKETING_INSTAGRAM_DATA_DIR)
os.environ.setdefault("WHISPER_MODEL", config.WHISPER_MODEL)
# Cache the Whisper model on the persistent volume so it is not re-downloaded
# from HuggingFace on every cold start / restart.
os.environ.setdefault("HF_HOME", str(Path(config.MARKETING_DATA_DIR) / ".hf_cache"))

from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: E402
from apscheduler.triggers.cron import CronTrigger  # noqa: E402

import marketing_pipeline.bootstrap as _bootstrap_mod  # noqa: E402
from marketing_pipeline.bootstrap import ensure_pipeline_data  # noqa: E402
from marketing_pipeline.tiktok.orchestrator import (  # noqa: E402
    run_display_snapshots,
    run_export,
    run_ocr_batch,
    run_refresh_comments,
    run_studio_listen_production,
    run_sync_playbooks_cmd,
    run_sync_supabase,
)
from marketing_pipeline.tiktok.stages.display_api import DisplayApiNotConfigured  # noqa: E402
from marketing_pipeline.tiktok.stages.transcribe_video import transcribe_video  # noqa: E402
from marketing_pipeline.tiktok.stages.write_per_video_complete import existing_complete_ids  # noqa: E402
from marketing_pipeline.tiktok.stages.write_master_transcripts import (  # noqa: E402
    write_master_transcripts,
)
from marketing_pipeline.instagram.orchestrator import (  # noqa: E402
    run_export as run_instagram_export,
    run_sync_supabase as run_instagram_sync_supabase,
)

from common.supabase_client import get_client  # noqa: E402
from social_metrics import (  # noqa: E402
    TARGETS, TIKTOK_PEERS, refresh as refresh_social_metrics, refresh_public_peers, write_snapshot,
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


def _transcribe_observed_docmap_posts(posts: dict[str, str]) -> dict:
    """Transcribe a bounded set of already captured posts, without a stats refresh."""
    have = existing_complete_ids()
    attempted = 0
    for post_id, url in posts.items():
        if post_id in have:
            continue
        transcribe_video(post_id, {"webpage_url": url}, model_size=config.WHISPER_MODEL)
        attempted += 1
        if attempted == 8:
            break
    if attempted:
        write_master_transcripts(refresh_metrics=False)
    return {"attempted": attempted}


_SOCIAL_JOB_LOCK = Lock()


def _refresh_social_pipeline(*, include_ocr: bool = False, include_peers: bool = False) -> dict:
    targets = {platform: handles for platform, handles in TARGETS.items()
               if platform != "instagram" or not config.SKIP_INSTAGRAM}
    if include_peers:
        targets["tiktok"] += TIKTOK_PEERS

    observed_docmap_posts: dict[str, str] = {}

    def enrich(captured):
        results = {}
        for platform, primary in (("tiktok", "docmap"), ("instagram", "docmapuk")):
            target = f"{platform}:{primary}"
            if target not in captured:
                continue
            if captured[target]["status"] != "saved":
                results[platform] = {"status": "blocked", "reason": "primary_capture_incomplete"}
                continue
            try:
                # Legacy analysis is intentionally separate from the fresh
                # snapshot layer. Do not pull another unpersisted count batch.
                if platform == "tiktok":
                    try:
                        run_refresh_comments()
                    except Exception as exc:
                        logger.warning("Optional comment refresh failed: %s", type(exc).__name__)
                    if not config.SKIP_TRANSCRIBE:
                        try:
                            _transcribe_observed_docmap_posts(observed_docmap_posts)
                        except Exception as exc:
                            logger.warning("Optional transcription failed: %s", type(exc).__name__)
                    run_export()
                    run_sync_supabase()
                    run_sync_playbooks_cmd()
                    if include_ocr:
                        run_ocr_batch()
                else:
                    run_instagram_export()
                    run_instagram_sync_supabase()
                results[platform] = {"status": "ok"}
            except Exception as exc:
                results[platform] = {"status": "failed", "error_type": type(exc).__name__}
        return results

    client = get_client()
    def save(platform, handle, observation, captured_at):
        write_snapshot(client, platform, handle, observation, captured_at)
        if (platform, handle) == ("tiktok", "docmap"):
            observed_docmap_posts[observation[0]] = observation[1]

    return refresh_social_metrics(
        targets=targets,
        save=save,
        enrich=enrich,
    )


def _run_social_pipeline(*, include_ocr: bool = False, include_peers: bool = False) -> dict:
    if not _SOCIAL_JOB_LOCK.acquire(blocking=False):
        return {"status": "skipped_overlap"}
    try:
        return _refresh_social_pipeline(include_ocr=include_ocr, include_peers=include_peers)
    finally:
        _SOCIAL_JOB_LOCK.release()


def _run_public_peer_metrics() -> dict:
    if not _SOCIAL_JOB_LOCK.acquire(blocking=False):
        return {"status": "skipped_overlap"}
    try:
        client = get_client()
        return refresh_public_peers(save=lambda *args: write_snapshot(client, *args))
    finally:
        _SOCIAL_JOB_LOCK.release()


def main() -> None:
    logger.info("marketing_pipeline.bootstrap at %s", _bootstrap_mod.__file__)
    bootstrap = ensure_pipeline_data()
    logger.info("Pipeline data: %s", bootstrap)
    if bootstrap.get("error"):
        logger.warning(
            "Pipeline seed failed — cron jobs may fail until MARKETING_DATA_DIR is populated"
        )

    scheduler = BlockingScheduler(timezone="UTC")

    # Opt-in only. The owner selects a directory on the persistent volume.
    x_watch_state = os.getenv("X_ALGORITHM_WATCH_STATE_DIR", "").strip()
    if x_watch_state:
        from x_algorithm_watch import run_watch

        scheduler.add_job(
            _safe("x_algorithm_watch", lambda: run_watch(Path(x_watch_state))),
            CronTrigger(day_of_week="mon", hour=6, minute=0),
            id="x_algorithm_watch",
            replace_existing=True,
            max_instances=1,
        )

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
        _safe("social_marketing", _run_social_pipeline),
        CronTrigger(hour=3, minute=30),
        id="social_marketing",
        replace_existing=True,
    )

    scheduler.add_job(
        _safe(
            "social_weekly",
            lambda: _run_social_pipeline(include_ocr=True),
        ),
        CronTrigger(day_of_week="sun", hour=2, minute=0),
        id="social_weekly",
        replace_existing=True,
    )

    scheduler.add_job(
        _safe("public_tiktok_peer_metrics", _run_public_peer_metrics),
        CronTrigger(hour=9, minute=0),
        id="public_tiktok_peer_metrics",
        replace_existing=True,
    )

    def _run_display_snapshots() -> dict:
        try:
            return run_display_snapshots(update_latest=True)
        except DisplayApiNotConfigured as exc:
            logger.warning("tiktok_display_snapshots skipped: %s", exc)
            return {"skipped": True, "reason": str(exc)}

    scheduler.add_job(
        _safe("tiktok_display_snapshots", _run_display_snapshots),
        CronTrigger(hour="*/3", minute=15),
        id="tiktok_display_snapshots",
        replace_existing=True,
    )

    if not config.SKIP_STUDIO_LISTEN:
        # 2x/week, quiet UTC morning — small batch + long pauses (see STUDIO_LISTEN_*)
        scheduler.add_job(
            _safe("tiktok_studio_listen", run_studio_listen_production),
            CronTrigger(day_of_week="tue,fri", hour=5, minute=45),
            id="tiktok_studio_listen",
            replace_existing=True,
        )
        logger.info(
            "Studio listen enabled (Tue/Fri 05:45 UTC, recent=%s)",
            os.getenv("STUDIO_LISTEN_RECENT", "15"),
        )
    else:
        logger.info("SKIP_STUDIO_LISTEN=true — Studio Playwright job disabled")

    if not config.SKIP_HCA:
        scheduler.add_job(
            _safe("hca_sqlite_migration", run_hca_migration),
            CronTrigger(hour=4, minute=0),
            id="hca_sqlite_migration",
            replace_existing=True,
        )
    else:
        logger.info("SKIP_HCA=true — HCA migration job disabled")

    def _run_creator_corpus_drain() -> dict:
        if config.SKIP_CREATOR_CORPUS:
            logger.info("SKIP_CREATOR_CORPUS=true — corpus drain disabled")
            return {"skipped": True, "reason": "SKIP_CREATOR_CORPUS=true"}
        from marketing_pipeline.creators.commands import run_drain

        return run_drain(deadline="02:45")

    def _run_creator_corpus_refresh() -> dict:
        if config.SKIP_CREATOR_CORPUS:
            logger.info("SKIP_CREATOR_CORPUS=true — Sunday corpus refresh disabled")
            return {"skipped": True, "reason": "SKIP_CREATOR_CORPUS=true"}
        from marketing_pipeline.creators.commands import run_sunday_refresh

        return run_sunday_refresh()

    if not config.SKIP_CREATOR_CORPUS:
        scheduler.add_job(
            _safe("creator_corpus_drain", _run_creator_corpus_drain),
            CronTrigger(hour=1, minute=0),
            id="creator_corpus_drain",
            replace_existing=True,
        )
        scheduler.add_job(
            _safe("creator_corpus_refresh", _run_creator_corpus_refresh),
            CronTrigger(day_of_week="sun", hour=0, minute=30),
            id="creator_corpus_refresh",
            replace_existing=True,
        )
        logger.info("Creator corpus drain enabled (01:00 UTC, deadline 02:45)")
    else:
        logger.info("SKIP_CREATOR_CORPUS=true — creator corpus drain/refresh disabled")

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
        logger.info("RUN_ON_START enabled — running social pipeline once now")
        _safe("tiktok_marketing_on_start", _run_social_pipeline)()

    scheduler.start()


if __name__ == "__main__":
    if sys.argv[1:] == ["--public-peer-metrics-once"]:
        result = _run_public_peer_metrics()
        logger.info("Public peer observation outcomes: %s", result)
        sys.exit(0 if result and all(isinstance(item, dict) and item.get("status") == "saved"
                                        for item in result.values()) else 1)
    if sys.argv[1:] == ["--social-metrics-once"]:
        results = _run_social_pipeline(include_peers=True)
        logger.info("Social metric verification outcomes: %s", results)
        incomplete = [target for target, item in results.items()
                      if target != "enrichment" and (not isinstance(item, dict) or item.get("status") != "saved")]
        sys.exit(1 if incomplete else 0)
    if sys.argv[1:]:
        sys.exit("usage: python main.py [--public-peer-metrics-once|--social-metrics-once]")
    main()
