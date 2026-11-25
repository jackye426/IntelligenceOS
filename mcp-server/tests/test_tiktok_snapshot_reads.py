"""Regression tests at Claude's registered MCP read entry points."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import main
from common import supabase_client


def post(account, video_id, views, platform="tiktok"):
    return {
        "platform": platform, "platform_post_id": video_id, "account_handle": account,
        "owner_scope": "docmap" if account == "docmap" else f"peer:{account}",
        "posted_at": "2026-11-23T00:00:00+00:00",
        "metrics": {"views": views, "shares": 88, "duration_sec": 10},
    }


def snapshot(account, video_id, views, age=1, source="yt_dlp"):
    return {
        **post(account, video_id, views), "metrics": {"views": views, "likes": 0},
        "captured_at": (datetime.now(timezone.utc) - timedelta(hours=age)).isoformat(),
        "source": source,
    }


class FakeClient:
    def __init__(self):
        self.requests = []
        self.fail_snapshots = False
        self.ignore_base_filters = False
        self.posts = [post("docmap", "a", 1), post("docmap", "b", 5),
                      post("docmap", "c", 3), post("endobowelsurgeon", "a", 800),
                      post("drleewarren", "a", 900), post("docmap", "ig", 200, "instagram")]
        self.owned = [snapshot("docmap", "a", 100), snapshot("docmap", "a", 99, age=2),
                      snapshot("docmap", "a", 7000, source="display_api"),
                      snapshot("endobowelsurgeon", "a", 500),
                      snapshot("docmap", "c", 30, age=49)]
        self.peer = [snapshot("drleewarren", "a", 400),
                     snapshot("robotic.endosurgeon", "a", 600)]

    def table(self, name):
        self.requests.append((name, []))
        return FakeQuery(self, name, self.requests[-1][1])


class FakeQuery:
    def __init__(self, db, table, filters):
        self.db, self.name, self.filters = db, table, filters
        self.rows = {
            "content_posts": db.posts, "latest_social_metric_snapshots": db.owned,
            "latest_public_tiktok_peer_metrics": db.peer,
        }.get(table, [])

    def select(self, _):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        if self.name == "content_posts" and not self.db.ignore_base_filters:
            self.rows = [r for r in self.rows if r.get(field) == value]
        return self

    def or_(self, clause):
        assert clause == "platform.neq.tiktok,and(platform.eq.tiktok,account_handle.eq.docmap,owner_scope.eq.docmap)"
        self.filters.append(("or", clause))
        self.rows = [r for r in self.rows if r["platform"] != "tiktok"
                     or (r["account_handle"], r["owner_scope"]) == ("docmap", "docmap")]
        return self

    def in_(self, field, values):
        self.filters.append((field, values))
        # Intentionally return all fixture snapshot rows to exercise defensive validation.
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, start, end):
        self.rows = self.rows[start:end + 1]
        return self

    def limit(self, limit):
        self.rows = self.rows[:limit]
        return self

    def insert(self, _):
        return self

    def execute(self):
        if self.name.startswith("latest_") and self.db.fail_snapshots:
            raise RuntimeError("snapshot view unavailable")
        return SimpleNamespace(data=self.rows)


@pytest.fixture
def db(monkeypatch):
    db = FakeClient()
    monkeypatch.setattr(supabase_client, "_client", db)
    return db


def test_cohort_tool_uses_scoped_latest_snapshot_and_labels_fallback(db):
    result = main.get_tiktok_cohort_tool(since="2026-11-01")
    first, stale, cached = result["posts"]
    assert result["account"] == "docmap"
    assert first["video_id"] == "a"
    assert first["metrics"] == {"views": 100, "likes": 0, "duration_sec": 10}
    assert first["engagement"] is None
    assert first["saves_per_1k_views"] is None
    assert first["metrics_provenance"]["source"] == "yt_dlp"
    assert first["metrics_provenance"]["captured_at"]
    assert first["metrics_provenance"]["freshness"] == "fresh"
    assert stale["metrics_provenance"]["freshness"] == "stale"
    assert cached["metrics_provenance"] == {
        "source": "content_posts.metrics", "captured_at": None, "freshness": "cached_unknown_age",
    }
    snapshots = [request for request in db.requests if request[0].startswith("latest_")]
    assert len(snapshots) == 1
    assert set(map(tuple, snapshots[0][1][:-1])) == {
        ("platform", "tiktok"), ("source", "yt_dlp"), ("account_handle", "docmap"),
        ("owner_scope", "docmap"),
    }
    assert snapshots[0][1][-1] == ("platform_post_id", ["a", "b", "c"])


def test_generic_tool_is_docmap_only_for_tiktok_even_cross_platform(db):
    only_tiktok = main.get_content_performance_tool(platform="tiktok")
    assert all(r["account_handle"] == "docmap" for r in only_tiktok)
    assert only_tiktok[0]["views"] == 100
    combined = main.get_content_performance_tool()
    assert [r["platform"] for r in combined] == ["instagram", "tiktok", "tiktok", "tiktok"]
    assert combined[0]["views"] == 200
    assert combined[0]["metrics_provenance"] is None


def test_generic_tool_rejects_mixed_scope_without_fetching_snapshots(db):
    db.ignore_base_filters = True
    with pytest.raises(RuntimeError, match="out-of-scope"):
        main.get_content_performance_tool(platform="tiktok")
    assert not any(name.startswith("latest_") for name, _ in db.requests)


def test_snapshot_outage_is_not_silently_current(db):
    db.fail_snapshots = True
    result = main.get_content_performance_tool(platform="tiktok")
    assert all(r["metrics_provenance"]["freshness"] == "snapshot_unavailable" for r in result)
    assert all(r["metrics_provenance"]["captured_at"] is None for r in result)


@pytest.mark.parametrize(("account", "expected", "view"), [
    ("endobowelsurgeon", 500, "latest_social_metric_snapshots"),
    ("drleewarren", 400, "latest_public_tiktok_peer_metrics"),
])
def test_peer_mcp_packet_uses_its_own_snapshot(db, account, expected, view):
    result = main.get_peer_content_batch_tool(account=account, video_ids=["a"])
    assert result["posts"][0]["metrics"]["views"] == expected
    assert result["posts"][0]["metrics_provenance"]["freshness"] == "fresh"
    assert [name for name, _ in db.requests if name.startswith("latest_")] == [view]


def test_registered_tools_expose_distinct_purpose_and_latest_counts(db):
    import asyncio

    async def read():
        registered = {tool.name: tool.description for tool in await main.mcp.list_tools()}
        assert "date filters and tiers" in registered["get_tiktok_cohort_tool"]
        assert "TikTok results are DocMap-only" in registered["get_content_performance_tool"]
        cohort = await main.mcp.call_tool("get_tiktok_cohort_tool", {"limit": 1})
        performance = await main.mcp.call_tool(
            "get_content_performance_tool", {"platform": "tiktok", "limit": 1}
        )
        return cohort, performance

    cohort, performance = asyncio.run(read())
    for payload in (cohort, performance):
        assert "yt_dlp" in str(payload)
        assert "captured_at" in str(payload)
        assert "100" in str(payload)
