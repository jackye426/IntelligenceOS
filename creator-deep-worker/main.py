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
import subprocess
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


def verify_schema() -> bool:
    script = REPO / "scripts" / "verify-supabase-schema.py"
    completed = subprocess.run(
        [sys.executable, str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        HEALTH["schema_verify"] = "failed"
        HEALTH["schema_verify_error"] = (completed.stdout or completed.stderr or "")[-500:]
        return False
    HEALTH["schema_verify"] = "ok"
    return True


def _client():
    from supabase import create_client

    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["SUPABASE_KEY"],
    )


def _refresh_health() -> None:
    HEALTH["listing_paused"] = listing_paused()
    HEALTH["skip"] = SKIP_CREATOR_DEEP
    HEALTH["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if SKIP_CREATOR_DEEP or not os.getenv("SUPABASE_URL"):
        return
    try:
        client = _client()
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
        "creators",
        "promote-peer",
        "--handle",
        handle,
        "--quality",
        quality,
    ]
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [
                str(REPO / "marketing-pipeline" / "src"),
                os.environ.get("PYTHONPATH", ""),
            ]
        ),
    }
    logger.info("subprocess ingest (parent does not activate_account): %s", cmd)
    completed = subprocess.run(cmd, check=False, capture_output=True, text=True, env=env)
    payload: dict[str, Any] = {
        "handle": handle,
        "quality": quality,
        "returncode": completed.returncode,
        "skipped": False,
    }
    if completed.returncode != 0:
        payload["stderr"] = (completed.stderr or "")[-500:]
        payload["status"] = "failed"
        return payload
    try:
        payload["result"] = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        payload["stdout"] = completed.stdout
    payload["status"] = "completed"
    return payload


def _run_write_brief(handle: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "-m",
        "marketing_pipeline",
        "creators",
        "write-brief",
        "--handle",
        handle,
    ]
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [
                str(REPO / "marketing-pipeline" / "src"),
                os.environ.get("PYTHONPATH", ""),
            ]
        ),
    }
    completed = subprocess.run(cmd, check=False, capture_output=True, text=True, env=env)
    return {"handle": handle, "returncode": completed.returncode, "kind": "write_brief"}


def _finish_item(client, item: dict[str, Any], *, status: str, result: dict[str, Any]) -> None:
    client.table("creator_deep_job_items").update(
        {
            "status": status,
            "result": result,
            "heartbeat_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", item["id"]).execute()


def _claim(kind: str) -> list[dict[str, Any]]:
    client = _client()
    claimed = client.rpc(
        "creator_claim_deep_job_items",
        {
            "p_limit": 1,
            "p_worker_id": worker_id(),
            "p_stale_seconds": DEEP_STALE_SECONDS,
            "p_kind": kind,
        },
    ).execute()
    return claimed.data or []


def process_one(*, pause_listing: bool) -> bool:
    """Claim at most one item. Returns True if work ran."""
    kind = "write_brief" if pause_listing else None
    items = _claim(kind) if kind else _claim("deep_ingest")
    if not items and not pause_listing:
        items = _claim("write_brief")
    if not items:
        return False
    item = items[0]
    payload = item.get("payload") or {}
    handle = payload.get("handle") or ""
    quality = payload.get("quality") or "auto"
    HEALTH["active_ingest"] = handle or item.get("id")
    client = _client()
    try:
        if item.get("kind") == "write_brief":
            result = _run_write_brief(handle)
        else:
            result = _run_ingest_subprocess(handle, quality)
        ok = result.get("returncode", 1) == 0 or result.get("status") == "completed"
        _finish_item(client, item, status="succeeded" if ok else "failed", result=result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("deep item failed")
        _finish_item(client, item, status="failed", result={"error": str(exc)})
    finally:
        HEALTH["active_ingest"] = None
    return True


def _claim_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        HEALTH["listing_paused"] = listing_paused()
        if SKIP_CREATOR_DEEP:
            HEALTH["active_ingest"] = None
            stop.wait(30)
            continue
        if not os.getenv("SUPABASE_URL"):
            HEALTH["note"] = "no supabase"
            stop.wait(30)
            continue
        try:
            worked = process_one(pause_listing=listing_paused())
        except Exception:
            logger.exception("claim loop error")
            worked = False
        stop.wait(5 if worked else 30)


def main() -> None:
    if DEEP_STALE_SECONDS < 14400:
        raise SystemExit("creator-deep-worker refuses GTM 600s stale window")
    if not SKIP_CREATOR_DEEP and not verify_schema():
        raise SystemExit("creator-deep-worker refuses to start: schema verify failed")

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
