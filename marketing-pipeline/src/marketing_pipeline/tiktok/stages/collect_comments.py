"""Fetch TikTok comments from catalog video IDs."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from marketing_pipeline import config
from marketing_pipeline.tiktok.stages.collect_catalog import load_catalog

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def fetch_comment_page(aweme_id: str, cursor: int = 0, count: int = 50) -> dict:
    query = urllib.parse.urlencode(
        {
            "aid": "1988",
            "aweme_id": aweme_id,
            "count": str(count),
            "cursor": str(cursor),
        }
    )
    url = f"https://www.tiktok.com/api/comment/list/?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Referer": "https://www.tiktok.com/",
            "Accept": "application/json, text/plain, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


class RequestBudgetExhausted(RuntimeError):
    """Raised when a run hits its per-run request ceiling."""


class _Budget:
    """Per-run request ceiling.

    The comment endpoint is unauthenticated. At DocMap's ~70 videos that is fine;
    across a 1,372-post peer catalog an uncapped run issues ~14,000 requests and
    gets blocked partway through, so every run declares a ceiling.
    """

    def __init__(self, limit: int | None) -> None:
        self.limit = limit
        self.used = 0

    def spend(self) -> None:
        if self.limit is not None and self.used >= self.limit:
            raise RequestBudgetExhausted(f"Request budget of {self.limit} exhausted.")
        self.used += 1


def fetch_all_comments(
    aweme_id: str,
    max_comments: int = 500,
    *,
    start_cursor: int = 0,
    budget: "_Budget | None" = None,
    max_retries: int = 5,
) -> tuple[list[dict], int, bool]:
    """Page comments for one video.

    Returns (comments, next_cursor, exhausted). `exhausted` is True when the
    server said there is no more; a False with a non-zero cursor means the run
    stopped early and can be resumed from that cursor.
    """
    out: list[dict] = []
    cursor = start_cursor
    retries = 0
    while len(out) < max_comments:
        try:
            if budget is not None:
                budget.spend()
            data = fetch_comment_page(aweme_id, cursor=cursor, count=50)
            retries = 0
        except RequestBudgetExhausted:
            return out, cursor, False
        except urllib.error.HTTPError as exc:
            # Exponential backoff with a longer ceiling than the old 3 tries:
            # 429 on this endpoint is common and recoverable.
            if exc.code in (403, 429, 500, 502, 503) and retries < max_retries:
                retries += 1
                time.sleep(min(2**retries, 60))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if retries < max_retries:
                retries += 1
                time.sleep(min(2**retries, 60))
                continue
            raise
        comments = data.get("comments") or []
        if not comments:
            break
        for item in comments:
            out.append(
                {
                    "cid": item.get("cid"),
                    "text": (item.get("text") or "").strip(),
                    "digg_count": int(item.get("digg_count") or 0),
                    "reply_comment_total": int(item.get("reply_comment_total") or 0),
                    "create_time": item.get("create_time"),
                }
            )
            if len(out) >= max_comments:
                break
        if not data.get("has_more"):
            return out, cursor, True
        cursor = int(data.get("cursor") or 0)
        time.sleep(0.35)
    return out, cursor, False


def _file_age_days(path: Path) -> float:
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - mtime).total_seconds() / 86400


def needs_refresh(
    video_id: str,
    *,
    catalog_comment_count: int | None = None,
    stale_days: int | None = None,
) -> bool:
    path = config.COMMENTS_RAW_DIR / f"{video_id}.json"
    if not path.exists():
        return True
    days = stale_days if stale_days is not None else config.COMMENT_STALE_DAYS
    if _file_age_days(path) > days:
        return True
    if catalog_comment_count is not None:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if catalog_comment_count > len(existing):
                return True
        except json.JSONDecodeError:
            return True
    return False


RESUME_FILENAME = "comment_fetch_resume.json"


def _resume_path() -> Path:
    return config.COMMENTS_RAW_DIR / RESUME_FILENAME


def load_resume_state() -> dict[str, Any]:
    path = _resume_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_resume_state(state: dict[str, Any]) -> None:
    config.COMMENTS_RAW_DIR.mkdir(parents=True, exist_ok=True)
    _resume_path().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_comments(
    *,
    max_comments: int = 500,
    force: bool = False,
    stale_days: int | None = None,
    video_ids: list[str] | None = None,
    request_budget: int | None = None,
    resume: bool = True,
) -> dict[str, Any]:
    """Fetch comments for the active account.

    `video_ids` restricts the run to named videos, which is how peer comments are
    meant to be used: a targeted drill-down, never the whole library. A blocked
    or budget-limited run records its cursors so the next run continues instead
    of restarting.
    """
    catalog = load_catalog(config.CATALOG_DIR)
    config.COMMENTS_RAW_DIR.mkdir(parents=True, exist_ok=True)
    counts: dict[str, Any] = {
        "account": config.ACCOUNT,
        "seen": 0,
        "fetched": 0,
        "skipped": 0,
        "errors": 0,
        "partial": 0,
        "requests_used": 0,
        "budget_exhausted": False,
    }

    targets = list(video_ids) if video_ids else list(catalog.keys())
    if video_ids:
        missing = [v for v in targets if v not in catalog]
        if missing:
            counts["not_in_catalog"] = missing
        targets = [v for v in targets if v in catalog]

    state = load_resume_state() if resume else {}
    budget = _Budget(request_budget)

    for video_id in targets:
        row = catalog.get(video_id) or {}
        counts["seen"] += 1
        comment_count = int(row.get("comment_count") or 0)
        entry = state.get(video_id) or {}
        start_cursor = int(entry.get("cursor") or 0) if resume else 0
        already_done = bool(entry.get("complete")) and not force

        if already_done or (
            not force
            and start_cursor == 0
            and not needs_refresh(
                video_id,
                catalog_comment_count=comment_count,
                stale_days=stale_days,
            )
        ):
            counts["skipped"] += 1
            continue

        dest = config.COMMENTS_RAW_DIR / f"{video_id}.json"
        try:
            comments, next_cursor, done = fetch_all_comments(
                video_id,
                max_comments=max_comments,
                start_cursor=start_cursor,
                budget=budget,
            )
            if start_cursor and dest.exists():
                # Resumed run: append to what the earlier run already stored.
                try:
                    prior = json.loads(dest.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    prior = []
                seen_ids = {str(c.get("cid")) for c in prior}
                comments = prior + [c for c in comments if str(c.get("cid")) not in seen_ids]
            dest.write_text(json.dumps(comments, ensure_ascii=False, indent=2), encoding="utf-8")
            state[video_id] = {
                "cursor": 0 if done else next_cursor,
                "complete": done,
                "stored": len(comments),
            }
            if done:
                counts["fetched"] += 1
            else:
                counts["partial"] += 1
            time.sleep(0.5)
        except RequestBudgetExhausted:
            counts["budget_exhausted"] = True
            break
        except Exception:  # noqa: BLE001
            counts["errors"] += 1
            state[video_id] = {"cursor": start_cursor, "complete": False, "error": True}

    counts["requests_used"] = budget.used
    if resume:
        _save_resume_state(state)
    return counts
