"""Playwright listener for TikTok Studio /aweme/v2/data/insight/ responses.

Uses a persistent Chromium profile so you log in once (headed), then later
runs can reopen Studio pages and capture insight JSON without Display API.

Usage:
  python -m marketing_pipeline tiktok studio-listen --login
  python -m marketing_pipeline tiktok studio-listen --recent 20
  python -m marketing_pipeline tiktok studio-listen --video-id 7659... --ingest
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from marketing_pipeline import config

logger = logging.getLogger(__name__)

INSIGHT_PATH = "/aweme/v2/data/insight/"
STUDIO_ANALYTICS = "https://www.tiktok.com/tiktokstudio/analytics"
STUDIO_HOME = "https://www.tiktok.com/tiktokstudio"


def profile_dir() -> Path:
    path = config.DATA_ROOT / ".tiktok_studio_profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def capture_dir() -> Path:
    path = config.ANALYSIS_DIR / "studio_insight_captures"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _extract_aweme_id(url: str, body: dict[str, Any] | None = None) -> str | None:
    qs = parse_qs(urlparse(url).query)
    tr = qs.get("type_requests", [None])[0]
    if tr:
        try:
            reqs = json.loads(tr)
            for item in reqs:
                if isinstance(item, dict) and item.get("aweme_id"):
                    return str(item["aweme_id"])
        except json.JSONDecodeError:
            m = re.search(r'"aweme_id"\s*:\s*"(\d+)"', tr)
            if m:
                return m.group(1)
    if body:
        info = body.get("video_info") or {}
        if info.get("aweme_id"):
            return str(info["aweme_id"])
    return None


def _is_useful_insight(body: dict[str, Any]) -> bool:
    """Skip empty / rewards-only payloads."""
    keys = (
        "video_finish_rate_realtime",
        "video_per_duration_realtime",
        "video_traffic_source_percent_realtime",
        "video_retention_rate_realtime",
        "realtime_total_video_views",
    )
    return any(body.get(k) for k in keys)


class InsightCaptureBuffer:
    """Collect insight responses keyed by video id (keep richest payload)."""

    def __init__(self) -> None:
        self.by_video: dict[str, dict[str, Any]] = {}

    def add(self, video_id: str, body: dict[str, Any]) -> None:
        if not video_id or not _is_useful_insight(body):
            return
        existing = self.by_video.get(video_id)
        if existing is None or len(json.dumps(body)) > len(json.dumps(existing)):
            self.by_video[video_id] = body


def _attach_response_listener(page: Any, buffer: InsightCaptureBuffer) -> None:
    def on_response(response: Any) -> None:
        try:
            url = response.url or ""
            if INSIGHT_PATH not in url:
                return
            if response.status != 200:
                return
            body = response.json()
            if not isinstance(body, dict):
                return
            video_id = _extract_aweme_id(url, body)
            if video_id:
                buffer.add(video_id, body)
        except Exception as exc:  # noqa: BLE001
            logger.debug("insight listener skip: %s", exc)

    page.on("response", on_response)


def run_login(*, timeout_sec: int = 300) -> dict[str, Any]:
    """Open headed Studio so the user can log in; profile is persisted."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir()),
            headless=False,
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(STUDIO_HOME, wait_until="domcontentloaded")
        logger.info(
            "Log into TikTok Studio in the opened window. Waiting up to %ss…",
            timeout_sec,
        )
        deadline = time.time() + timeout_sec
        logged_in = False
        while time.time() < deadline:
            url = page.url or ""
            if "tiktokstudio" in url and "login" not in url.lower():
                # Heuristic: analytics nav or content present
                try:
                    if page.locator("text=Analytics").count() > 0 or "analytics" in url:
                        logged_in = True
                        break
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(2)
        context.close()
    return {
        "profile_dir": str(profile_dir()),
        "logged_in_heuristic": logged_in,
        "hint": "Re-run with --recent / --video-id after login if needed",
    }


def _load_recent_video_ids(limit: int) -> list[str]:
    """Prefer local catalog (newest first); fall back to dataset export."""
    from marketing_pipeline.tiktok.stages.collect_catalog import load_catalog

    try:
        catalog = load_catalog(config.CATALOG_DIR)
        keyed: list[tuple[str, str]] = []
        for vid, row in catalog.items():
            keyed.append(
                (
                    str(row.get("post_datetime_utc") or row.get("post_date_utc") or ""),
                    str(vid),
                )
            )
        keyed.sort(reverse=True)
        ids = [v for _, v in keyed if v.isdigit()][:limit]
        if ids:
            return ids
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog load failed: %s", exc)

    if config.DATASET_JSON.exists():
        data = json.loads(config.DATASET_JSON.read_text(encoding="utf-8"))
        videos = data.get("videos") or {}
        items = []
        for vid, rec in videos.items():
            posted = (rec.get("post") or {}).get("posted_at") or ""
            items.append((posted, str(vid)))
        items.sort(reverse=True)
        return [v for _, v in items[:limit]]
    return []


def _load_all_video_ids() -> list[str]:
    """Full catalog (newest first) for one-time baseline."""
    return _load_recent_video_ids(10_000)


def run_studio_listen(
    *,
    video_ids: list[str] | None = None,
    recent: int | None = None,
    all_videos: bool = False,
    headless: bool = True,
    settle_ms: int | None = None,
    pause_ms: int | None = None,
    pause_jitter_ms: int | None = None,
    ingest: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Visit Studio analytics pages and capture insight API JSON.

    Rate limits (defaults from config): settle on each page, then pause+jitter
    before the next video so production runs stay slow and small.

    Use ``all_videos=True`` once for a full-catalog baseline (no recent cap).
    Ongoing runs should use ``recent=15`` (default).
    """
    import random

    from playwright.sync_api import sync_playwright

    settle = settle_ms if settle_ms is not None else config.STUDIO_LISTEN_SETTLE_MS
    if pause_ms is not None:
        pause = pause_ms
    elif all_videos:
        pause = config.STUDIO_LISTEN_BASELINE_PAUSE_MS
    else:
        pause = config.STUDIO_LISTEN_PAUSE_MS
    jitter = (
        pause_jitter_ms
        if pause_jitter_ms is not None
        else config.STUDIO_LISTEN_PAUSE_JITTER_MS
    )

    ids = list(video_ids or [])
    if all_videos:
        ids = _load_all_video_ids()
    elif recent is not None or not ids:
        n = recent if recent is not None else config.STUDIO_LISTEN_RECENT
        ids = _load_recent_video_ids(n)
    if not ids:
        raise ValueError("No video ids — pass --video-id, --recent N, or --all")

    # Cap incremental runs only (never cap --all baseline)
    if not all_videos and video_ids is None:
        max_n = max(1, config.STUDIO_LISTEN_RECENT)
        if len(ids) > max_n:
            logger.info("Capping studio-listen from %s to %s videos", len(ids), max_n)
            ids = ids[:max_n]
    else:
        max_n = len(ids)

    logger.info(
        "studio-listen starting: %s videos (all=%s) settle=%sms pause=%sms",
        len(ids),
        all_videos,
        settle,
        pause,
    )

    buffer = InsightCaptureBuffer()
    errors: list[dict[str, str]] = []
    out_dir = capture_dir()
    saved: list[str] = []
    ingest_results: list[dict[str, Any]] = []

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir()),
            headless=headless,
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        _attach_response_listener(page, buffer)

        page.goto(STUDIO_HOME, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        if "login" in (page.url or "").lower():
            context.close()
            raise RuntimeError(
                "Not logged in. Run: python -m marketing_pipeline tiktok studio-listen --login"
            )

        for i, video_id in enumerate(ids):
            existing = out_dir / f"{video_id}.json"
            if all_videos and existing.exists() and existing.stat().st_size > 100:
                logger.info("studio-listen skip existing %s", video_id)
                # Keep resume skips out of "missing" in the final summary
                try:
                    buffer.by_video[video_id] = json.loads(
                        existing.read_text(encoding="utf-8")
                    )
                except json.JSONDecodeError:
                    pass
                saved.append(str(existing))
                if ingest:
                    try:
                        from marketing_pipeline.tiktok.stages.studio_insight import (
                            ingest_insight_json,
                        )

                        ingest_results.append(
                            ingest_insight_json(
                                existing, platform_post_id=video_id, dry_run=dry_run
                            )
                        )
                    except Exception as exc:  # noqa: BLE001
                        errors.append({"video_id": video_id, "error": f"ingest: {exc}"})
                continue

            url = f"{STUDIO_ANALYTICS}/{video_id}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(settle)
            except Exception as exc:  # noqa: BLE001
                errors.append({"video_id": video_id, "error": str(exc)})
                logger.warning("Failed to open %s: %s", video_id, exc)

            # Persist as we go so a long --all run survives mid-failure
            if video_id in buffer.by_video:
                path = out_dir / f"{video_id}.json"
                path.write_text(
                    json.dumps(buffer.by_video[video_id], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                saved.append(str(path))
                if ingest:
                    try:
                        from marketing_pipeline.tiktok.stages.studio_insight import (
                            ingest_insight_json,
                        )

                        ingest_results.append(
                            ingest_insight_json(
                                path, platform_post_id=video_id, dry_run=dry_run
                            )
                        )
                    except Exception as exc:  # noqa: BLE001
                        errors.append({"video_id": video_id, "error": f"ingest: {exc}"})

            if i < len(ids) - 1 and pause > 0:
                wait = pause + (random.randint(0, jitter) if jitter > 0 else 0)
                if (i + 1) % 5 == 0 or all_videos:
                    logger.info(
                        "studio-listen %s/%s captured_so_far=%s pause %sms",
                        i + 1,
                        len(ids),
                        len(buffer.by_video),
                        wait,
                    )
                page.wait_for_timeout(wait)

        context.close()

    # Mark baseline complete so ops can see it
    if all_videos and buffer.by_video:
        marker = config.ANALYSIS_DIR / "studio_insight_baseline_done.json"
        marker.write_text(
            json.dumps(
                {
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "requested": len(ids),
                    "captured": len(buffer.by_video),
                    "missing": [v for v in ids if v not in buffer.by_video],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    return {
        "requested": len(ids),
        "captured": len(buffer.by_video),
        "saved": saved,
        "capture_dir": str(out_dir),
        "ingest": ingest_results if ingest else None,
        "errors": errors,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "missing": [v for v in ids if v not in buffer.by_video],
        "all_videos": all_videos,
        "rate_limit": {
            "settle_ms": settle,
            "pause_ms": pause,
            "pause_jitter_ms": jitter,
            "max_videos": max_n,
        },
    }
