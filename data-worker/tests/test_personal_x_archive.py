from datetime import datetime, timezone
import sqlite3

import pytest

from personal_x_archive import HANDLES, run_archive

HANDLE = HANDLES[0]
NOW = datetime(2026, 11, 26, tzinfo=timezone.utc)


def post(pid, *, date="Wed Nov 25 12:00:00 +0000 2026", views=37, **fields):
    return {"id": str(pid), "text": f"Example {pid}", "createdAt": date, "viewCount": views,
            "author": {"userName": HANDLE, "id": "321", "protected": False}, **fields}


def payload(posts, cursor=None):
    return {"status": "success", "data": {"tweets": posts},
            "has_next_page": cursor is not None, "next_cursor": cursor}


def query(path, sql):
    with sqlite3.connect(path) as db:
        return db.execute(sql).fetchall()


def test_one_time_backfill_then_incremental_poll(tmp_path):
    path = tmp_path / "archive.db"
    calls = []
    def fetch(key, params):
        calls.append(params)
        assert key == "fixture"
        if "cursor" in params:
            return payload([post(6, date="Sun Jul 05 20:00:00 +0000 2026")])
        return payload([post(9, isQuote=True), post(8, isRetweet=True), post(7, isReply=True)], "cursor")
    run = lambda mode, get=fetch: run_archive(path, mode, "fixture", get=get, handles=(HANDLE,), now=NOW)
    assert run("backfill")[HANDLE]["status"] == "cutoff_reached"
    assert calls == [{"userName": HANDLE, "includeReplies": "false"},
                     {"userId": "321", "includeReplies": "false", "cursor": "cursor"}]
    calls.clear()
    assert run("backfill")[HANDLE]["status"] == "already_backfilled"
    assert calls == []
    assert query(path, "select id,kind from posts") == [("9", "quote")]
    def poll(key, params):
        assert params == {"userId": "321", "includeReplies": "false"}
        return payload([post(10, views=None), post(9, views=42)], "unused-cursor")
    assert run("poll", poll)[HANDLE]["new_posts"] == 1
    assert sorted(query(path, "select id from posts")) == [("10",), ("9",)]
    assert query(path, "select post_id,public_counts from metrics") == [("9", '{"viewCount": 42}')]


def test_no_key_or_seed_means_no_provider_calls(tmp_path):
    path = tmp_path / "archive.db"
    def forbidden(*_):
        pytest.fail("made provider call")
    with pytest.raises(ValueError, match="TWITTERAPI_IO_KEY"):
        run_archive(path, "backfill", "", get=forbidden)
    assert not path.exists()
    assert run_archive(path, "poll", "fixture", get=forbidden, handles=(HANDLE,), now=NOW)[HANDLE]["status"] == "backfill_required"


def test_provider_mismatch_and_page_fail_stop_before_account_write(tmp_path):
    path = tmp_path / "archive.db"
    def fetch(key, params):
        if "cursor" in params:
            return payload([post(8, author={"userName": "unrelated", "id": "321"})])
        return payload([post(9)], "cursor")
    with pytest.raises(ValueError, match="unexpected timeline author"):
        run_archive(path, "backfill", "fixture", get=fetch, handles=(HANDLE,), now=NOW)
    assert query(path, "select id from posts") == []
    assert query(path, "select handle from accounts") == []


def test_reports_page_cap_without_claiming_complete_coverage(tmp_path):
    path = tmp_path / "archive.db"
    def fetch(key, params):
        nxt = int(params.get("cursor", "0")) + 1
        return payload([post(nxt)], str(nxt))
    result = run_archive(path, "backfill", "fixture", get=fetch, handles=(HANDLE,), now=NOW)
    assert result[HANDLE]["status"] == "page_cap"
    assert result[HANDLE]["pages"] == 12
    assert run_archive(path, "poll", "fixture",
                       get=lambda *_: payload([post(99)]), handles=(HANDLE,),
                       now=NOW)[HANDLE]["status"] == "possible_gap"
