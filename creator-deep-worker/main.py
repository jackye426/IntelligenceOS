"""Creator-deep-worker — one peer ingest per process, then write_brief.

SKIP_CREATOR_DEEP defaults true until sql/014+015 verify and a Warren replay
produces a valid content_guidelines_v1 draft. Listing pauses 02:50–04:15 UTC
so DocMap's 03:30 TikTok cron keeps the IP.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(REPO / "marketing-pipeline" / "src"))

from dotenv import load_dotenv

load_dotenv(REPO / ".env.local")
load_dotenv(REPO / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("creator-deep-worker")

DEEP_STALE_SECONDS = 14400
LISTING_PAUSE_START = 2 * 60 + 50
LISTING_PAUSE_END = 4 * 60 + 15


def _truthy(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes"}


SKIP_CREATOR_DEEP = _truthy("SKIP_CREATOR_DEEP", "true")
HEALTH: dict[str, Any] = {
    "status": "ok",
    "service": "creator-deep-worker",
    "skip": SKIP_CREATOR_DEEP,
    "stale_seconds": DEEP_STALE_SECONDS,
    "queue_depth": 0,
    "items_older_than_24h": 0,
    "listing_paused": False,
    "active_ingest": None,
}


def listing_paused(now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    minutes = now.hour * 60 + now.minute
    return LISTING_PAUSE_START <= minutes < LISTING_PAUSE_END


def worker_id() -> str:
    return os.getenv("RAILWAY_REPLICA_ID") or f"{socket.gethostname()}-{os.getpid()}"


def _refresh_health() -> None:
    HEALTH["listing_paused"] = listing_paused()
    HEALTH["skip"] = SKIP_CREATOR_DEEP
    HEALTH["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if SKIP_CREATOR_DEEP or not os.getenv("SUPABASE_URL"):
        return
    try:
        from supabase import create_client

        client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["SUPABASE_KEY"],
        )
        queued = (
            client.table("creator_deep_job_items")
            .select("id", count="exact")
            .eq("status", "queued")
            .limit(1)
            .execute()
        )
        HEALTH["queue_depth"] = int(queued.count or 0)
    except Exception as exc:  # noqa: BLE001
        HEALTH["queue_error"] = str(exc)


class _Health(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        _refresh_health()
        body = json.dumps(HEALTH).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


def _run_ingest_subprocess(handle: str, quality: str) -> dict[str, Any]:
    """One ingest per OS process. Never activate_account in this parent."""
    cmd = [
        sys.executable,
        "-m",
        "marketing_pipeline",
        "tiktok",
        "--account",
        handle,
        "fetch-catalog",
    ]
    # Parent only forks. The child is the only process allowed to activate_account.
    logger.info("subprocess ingest (not yet started because SKIP): %s", cmd)
    return {"handle": handle, "quality": quality, "skipped": True, "reason": "stub_until_golden_replay"}


def _claim_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        HEALTH["listing_paused"] = listing_paused()
        if SKIP_CREATOR_DEEP:
            HEALTH["active_ingest"] = None
            stop.wait(30)
            continue
        if listing_paused():
            logger.info("listing pause 02:50–04:15 UTC — not claiming ingest items")
            stop.wait(30)
            continue
        # Production loop: rpc creator_claim_deep_job_items (stale 14400), fork one ingest, wait.
        HEALTH["note"] = "claim loop idle until SKIP_CREATOR_DEEP=false"
        stop.wait(30)


def main() -> None:
    if DEEP_STALE_SECONDS < 14400:
        raise SystemExit("creator-deep-worker refuses GTM 600s stale window")
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), _Health)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("health on :%s skip=%s stale=%s", port, SKIP_CREATOR_DEEP, DEEP_STALE_SECONDS)

    stop = threading.Event()

    def shutdown(_signum, _frame):
        stop.set()
        server.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    if SKIP_CREATOR_DEEP:
        logger.info("SKIP_CREATOR_DEEP=true — serving /health, not claiming jobs")
    _claim_loop(stop)


if __name__ == "__main__":
    main()
