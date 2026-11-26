"""Public-post collection for Jack's personal X research; no posting or account access."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

HANDLES = ("TrungTPhan", "tszzl", "ThePrimeagen", "VCBrags", "krazamtv",
           "levelsio", "badlogicgames", "steipete", "swyx", "edzitron")
API = "https://api.twitterapi.io/twitter/user/last_tweets"
METRICS = ("viewCount", "likeCount", "replyCount", "retweetCount", "quoteCount", "bookmarkCount")
BACKFILL_DAYS = 90
BACKFILL_PAGES = 12
POLL_PAGES = 3
ID = re.compile(r"\d{1,25}\Z")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch_page(key, params):
    url = f"{API}?{urlencode(params)}"
    req = Request(url, headers={"X-API-Key": key, "Accept": "application/json"})
    try:
        with build_opener(NoRedirect()).open(req, timeout=15) as response:
            raw = response.read(2_000_001)
    except HTTPError as exc:
        raise RuntimeError(f"timeline API HTTP {exc.code}") from None
    except URLError:
        raise RuntimeError("timeline API network failure") from None
    if len(raw) > 2_000_000:
        raise ValueError("timeline response too large")
    return json.loads(raw)


def post_time(value):
    if not isinstance(value, str):
        raise ValueError("missing publication time")
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        ts = parsedate_to_datetime(value)
    if ts.tzinfo is None:
        raise ValueError("publication time has no timezone")
    return ts.astimezone(timezone.utc)


def page(payload):
    if not isinstance(payload, dict) or payload.get("status", "success") != "success":
        raise ValueError("provider returned an error")
    inner = payload.get("data", payload)
    rows = inner.get("tweets") if isinstance(inner, dict) else None
    if not isinstance(rows, list) or len(rows) > 20:
        raise ValueError("unexpected timeline response")
    more = payload.get("has_next_page", inner.get("has_next_page"))
    cursor = payload.get("next_cursor", inner.get("next_cursor"))
    if type(more) is not bool or (more and (
        not isinstance(cursor, str) or not cursor or len(cursor) > 4096
    )):
        raise ValueError("invalid pagination")
    return rows, cursor if more else None


def normalize(row, handle, expected_id):
    if not isinstance(row, dict):
        raise ValueError("invalid timeline row")
    if row.get("isRetweet") is True or row.get("isReply") is True or row.get("retweeted_tweet"):
        return None
    author = row.get("author") or {}
    if author.get("protected") is True:
        return None
    name, uid = author.get("userName"), str(author.get("id", ""))
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,15}", name):
        raise ValueError("invalid timeline author")
    if (not ID.fullmatch(uid) or name.casefold() != handle.casefold()
            or (expected_id and uid != expected_id)):
        raise ValueError("unexpected timeline author")
    pid, text = str(row.get("id", "")), row.get("text")
    if not ID.fullmatch(pid) or not isinstance(text, str) or not text.strip() or len(text) > 40000:
        raise ValueError("invalid public post")
    ts = post_time(row.get("createdAt"))
    counters = {m: row[m] for m in METRICS if type(row.get(m)) is int and row[m] >= 0}
    kind = "quote" if row.get("isQuote") is True or row.get("quoted_tweet") else "original"
    return (pid, uid, ts, text, kind, counters)


def _schema(db):
    db.executescript("""
    create table if not exists accounts(handle text primary key, user_id text, backfill_status text,
      last_status text not null, checked_at text not null);
    create table if not exists posts(id text primary key, handle text not null, user_id text not null,
      published_at text not null, url text not null, text text not null, kind text not null);
    create table if not exists metrics(post_id text not null, day text not null,
      captured_at text not null, source text not null, public_counts text not null,
      primary key(post_id, day));
    """)


def run_archive(path, mode, key, *, get=fetch_page, handles=HANDLES, now=None):
    if not key.strip():
        raise ValueError("TWITTERAPI_IO_KEY is required")
    if mode not in ("backfill", "poll") or len(handles) > len(HANDLES) or any(h not in HANDLES for h in handles):
        raise ValueError("only the approved cohort and modes are supported")
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=BACKFILL_DAYS)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (path.parent / ".personal-x.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "skipped_overlap"}
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        with sqlite3.connect(path) as db:
            _schema(db)
            summary = {}
            for handle in handles:
                old = db.execute("select user_id,backfill_status from accounts where handle=?", (handle,)).fetchone()
                uid, seeded = old or (None, None)
                if mode == "backfill" and seeded:
                    summary[handle] = {"status": "already_backfilled", "coverage": seeded}
                    continue
                if mode == "poll" and not seeded:
                    summary[handle] = {"status": "backfill_required"}
                    continue
                known = {r[0] for r in db.execute("select id from posts where handle=?", (handle,))}
                cursor, seen_cursors, records = None, set(), {}
                reached_cutoff = False
                overlap = False
                for i in range(BACKFILL_PAGES if mode == "backfill" else POLL_PAGES):
                    args = {"userId": uid} if uid else {"userName": handle}
                    args["includeReplies"] = "false"
                    if cursor:
                        args["cursor"] = cursor
                    rows, cursor = page(get(key, args))
                    if cursor is not None and cursor in seen_cursors:
                        raise ValueError("repeated provider cursor")
                    seen_cursors.add(cursor)
                    dates = []
                    for row in rows:
                        item = normalize(row, handle, uid)
                        if item is None:
                            continue
                        pid, uid, ts, *_ = item
                        if ts > now + timedelta(minutes=5):
                            raise ValueError("future publication time")
                        dates.append(ts)
                        if ts < cutoff:
                            continue
                        overlap |= pid in known
                        records.setdefault(pid, item)
                    # Require overlap; keep the first matching page for a fresh counter observation.
                    reached_cutoff = bool(dates and min(dates) < cutoff)
                    if not cursor or reached_cutoff or (mode == "poll" and overlap):
                        break
                if mode == "backfill":
                    # An empty unpinned timeline is not proof that the account is valid.
                    if not records:
                        summary[handle] = {"status": "no_verified_posts", "pages": i + 1}
                        continue
                    status = "cutoff_reached" if reached_cutoff else "page_cap" if cursor else "timeline_end"
                    seeded = status
                else:
                    status = "possible_gap" if not overlap and known else "polled"
                captured = now.isoformat()
                for pid, author_id, ts, text, kind, counters in records.values():
                    db.execute("insert or ignore into posts values(?,?,?,?,?,?,?)",
                               (pid, handle, author_id, ts.isoformat(), f"https://x.com/{handle}/status/{pid}", text, kind))
                    if counters:
                        db.execute("insert into metrics values(?,?,?,?,?) on conflict(post_id, day) do update "
                                   "set captured_at=excluded.captured_at, public_counts=excluded.public_counts "
                                   "where excluded.captured_at >= metrics.captured_at",
                                   (pid, now.date().isoformat(), captured, "twitterapi.io", json.dumps(counters)))
                db.execute("insert or replace into accounts values(?,?,?,?,?)",
                           (handle, uid, seeded, status, captured))
                db.commit()
                summary[handle] = {"status": status, "posts": len(records),
                                   "new_posts": len(records.keys() - known), "pages": i + 1}
            return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("backfill", "poll"))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sample", action="store_true", help="Only try Trung Phan")
    args = parser.parse_args()
    try:
        result = run_archive(args.archive, args.mode, os.environ.get("TWITTERAPI_IO_KEY", ""),
                             handles=HANDLES[:1] if args.sample else HANDLES)
    except (ValueError, RuntimeError, sqlite3.Error) as exc:
        parser.exit(1, f"Collection stopped: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
