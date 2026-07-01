import logging
import traceback
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from db.models import ScrapeRun

logger = logging.getLogger(__name__)


def open_scrape_run(session: Session) -> ScrapeRun:
    run = ScrapeRun(started_at=datetime.now(timezone.utc), status="running")
    session.add(run)
    session.commit()
    session.refresh(run)
    logger.info("Scrape run %d started", run.scrape_run_id)
    return run


def close_scrape_run(session: Session, run: ScrapeRun, status: str = "completed", notes: str = "") -> None:
    run.completed_at = datetime.now(timezone.utc)
    run.status = status
    run.notes = notes
    session.commit()
    logger.info("Scrape run %d closed: status=%s", run.scrape_run_id, status)


def close_scrape_run_on_error(session: Session, run: ScrapeRun) -> None:
    notes = traceback.format_exc()
    close_scrape_run(session, run, status="error", notes=notes)
