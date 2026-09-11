"""Peer-library MCP tools: isolation, context budget, and honest measurement."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tools import peer_library as pl
from tools.tiktok_shared import cadence_fields, rolling_local_stats


def _rows(n=120, jump_at=60, low=1_000, high=50_000):
    start = date(2022, 1, 1)
    rows = []
    for i in range(n):
        day = start + timedelta(days=i)
        rows.append(
            {
                "platform_post_id": f"v{i:03d}",
                "posted_at": f"{day.isoformat()}T00:00:00+00:00",
                "post_url": f"https://www.tiktok.com/@drleewarren/video/v{i:03d}",
                "title": f"title {i}",
                "caption": f"caption number {i} with some words",
                "transcript": "spoken words here" if i % 2 == 0 else None,
                "metrics": {
                    "views": low if i < jump_at else high,
                    "likes": 10,
                    "comments": 2,
                    "shares": 1,
                    "duration_sec": 45,
                },
                "metadata": {
                    "hook_detail": {"spoken_hook": f"hook {i}", "hook_source": "whisper"},
                    "sample_plan": {
                        "is_deep_sample": i % 3 == 0,
                        "seed": 42,
                        "catalog_hash": "catalog-1",
                    },
                    "components": {"extraction": {"schema_version": "generic-clinician"}}
                    if i % 4 == 0
                    else None,
                },
            }
        )
    return rows


@pytest.fixture
def peer(monkeypatch):
    """Serve a synthetic peer catalog to every peer tool."""
    rows = _rows()
    monkeypatch.setattr(pl, "_all_rows", lambda account: rows if account != "docmap" else [])
    monkeypatch.setattr(pl, "log_tool_call", lambda **kwargs: None)
    return rows


# --------------------------------------------------------------- isolation ---


def test_peer_tools_refuse_docmap():
    for call in (
        lambda: pl.get_peer_library_brief("docmap"),
        lambda: pl.get_peer_era_summary("docmap"),
        lambda: pl.get_peer_corpus_manifest("docmap"),
        lambda: pl.get_peer_content_batch("docmap", ["v001"]),
        lambda: pl.get_peer_comments("docmap", ["v001"]),
    ):
        with pytest.raises(pl.PeerAccountError, match="owned library"):
            call()


def test_peer_tools_require_an_account():
    with pytest.raises(pl.PeerAccountError, match="account is required"):
        pl.get_peer_corpus_manifest("")


def test_handle_is_normalised(peer):
    result = pl.get_peer_corpus_manifest("@DrLeeWarren")
    assert result["account"] == "drleewarren"


# ---------------------------------------------------------- context budget ---


def test_manifest_rows_carry_no_captions_or_titles(peer):
    result = pl.get_peer_corpus_manifest("drleewarren", limit=10)
    for row in result["posts"]:
        assert "caption" not in row
        assert "title" not in row
    assert result["captions_included"] is False


def test_captions_require_a_bounded_id_list(peer):
    with pytest.raises(pl.PeerAccountError, match="video_ids"):
        pl.get_peer_corpus_manifest("drleewarren", include_captions=True)


def test_manifest_can_return_only_the_saved_deep_sample(peer):
    result = pl.get_peer_corpus_manifest("drleewarren", sample_only=True)
    assert result["total_rows"] == 40
    assert result["sample_only"] is True
    assert all(row["is_deep_sample"] for row in result["posts"])
    ok = pl.get_peer_corpus_manifest(
        "drleewarren", include_captions=True, video_ids=["v001", "v002"]
    )
    assert ok["returned_rows"] == 2
    assert ok["posts"][0]["caption"]


def test_pagination_makes_truncation_visible(peer):
    first = pl.get_peer_corpus_manifest("drleewarren", limit=50)
    assert first["total_rows"] == 120
    assert first["returned_rows"] == 50
    assert first["has_more"] is True
    assert first["next_cursor"] == 50

    last = pl.get_peer_corpus_manifest("drleewarren", cursor=100, limit=50)
    assert last["returned_rows"] == 20
    assert last["has_more"] is False
    assert last["next_cursor"] is None


def test_batch_is_capped(peer):
    with pytest.raises(pl.PeerAccountError, match="Batch limit"):
        pl.get_peer_content_batch("drleewarren", [f"v{i:03d}" for i in range(30)])


def test_batch_requires_ids(peer):
    with pytest.raises(pl.PeerAccountError, match="video_ids is required"):
        pl.get_peer_content_batch("drleewarren", [])


# ------------------------------------------------------------- deep packets ---


def test_batch_returns_full_text_and_flags_missing(peer):
    result = pl.get_peer_content_batch("drleewarren", ["v000", "v002", "nope"])
    assert result["returned"] == 2
    assert result["not_found"] == ["nope"]
    packet = result["posts"][0]
    assert packet["caption"]
    assert packet["transcript"] == "spoken words here"
    assert packet["spoken_hook"] == "hook 0"


def test_component_labels_are_marked_as_derived(peer):
    result = pl.get_peer_content_batch("drleewarren", ["v000"])
    annotation = result["posts"][0]["derived_annotation"]
    assert "not ground truth" in annotation["source"]
    assert annotation["schema_version"] == "generic-clinician"
    assert "disagree" in annotation["guidance"]


def test_ocr_scope_is_declared_on_every_packet(peer):
    result = pl.get_peer_content_batch("drleewarren", ["v000", "v001"])
    for packet in result["posts"]:
        assert packet["ocr_scope"] == "opening_frames"
        assert "pacing" in packet["ocr_note"].lower()


# -------------------------------------------------------------- measurement ---


def test_eras_are_detected_from_the_view_shift(peer):
    summary = pl.get_peer_era_summary("drleewarren")
    eras = summary["eras"]
    assert len(eras) >= 2
    assert eras[0]["median_views"] < eras[-1]["median_views"]
    assert all("_start" not in e for e in eras), "internal indices must not leak"
    assert [era["era"] for era in eras] == ["era_1", "era_2", "era_3"]
    assert all(era["label_status"] == "neutral_statistical_segment" for era in eras)


def test_era_summary_states_what_cannot_be_measured(peer):
    summary = pl.get_peer_era_summary("drleewarren")
    assert "growth_causation" in summary["not_measurable"]
    assert "pacing_and_edit_rhythm" in summary["not_measurable"]
    assert summary["duration_distribution"]["31-60s"] == 120
    assert summary["monthly_trend"]
    assert "median_views" in summary["monthly_trend"][0]


def test_library_brief_reports_isolation_and_real_sample_coverage(peer):
    brief = pl.get_peer_library_brief("drleewarren")
    assert brief["isolation_audit"]["safe_to_analyse"] is True
    assert brief["coverage"]["deep_sample"] == 40
    assert brief["coverage"]["deep_sample_share"] == pytest.approx(1 / 3, abs=0.001)
    assert brief["context_budget"]["estimated_transcript_tokens"] > 0


def test_ratios_are_local_not_global(peer):
    """Old low-view posts must not read as underperforming just for being old."""
    result = pl.get_peer_corpus_manifest("drleewarren", limit=400)
    by_id = {r["video_id"]: r for r in result["posts"]}
    assert by_id["v010"]["local_tier"] == "typical"
    assert by_id["v110"]["local_tier"] == "typical"
    assert by_id["v010"]["window_n"] == 40


def test_missing_metrics_stay_null(peer, monkeypatch):
    rows = _rows(n=60)
    rows[0]["metrics"] = {"views": 1000, "duration_sec": None, "saves": None}
    monkeypatch.setattr(pl, "_all_rows", lambda account: rows)
    result = pl.get_peer_corpus_manifest("drleewarren", limit=60)
    row = next(r for r in result["posts"] if r["video_id"] == "v000")
    assert row["duration_sec"] is None
    assert row["saves"] is None


def test_small_catalog_reports_insufficient_window(monkeypatch):
    rows = _rows(n=6)
    monkeypatch.setattr(pl, "_all_rows", lambda account: rows)
    monkeypatch.setattr(pl, "log_tool_call", lambda **kwargs: None)
    result = pl.get_peer_corpus_manifest("drleewarren")
    assert all(r["local_tier"] == "insufficient_window" for r in result["posts"])
    assert all(r["local_views_ratio"] is None for r in result["posts"])


def test_cadence_fields_are_deterministic(peer):
    result = pl.get_peer_corpus_manifest("drleewarren", limit=5)
    rows = {r["video_id"]: r for r in result["posts"]}
    assert rows["v001"]["days_since_previous_post"] == 1
    assert rows["v001"]["posts_in_same_week"] >= 1


def test_brief_is_a_map_not_a_thesis(peer):
    brief = pl.get_peer_library_brief("drleewarren")
    assert brief["catalog_size"] == 120
    assert brief["date_range"]["first"] < brief["date_range"]["last"]
    assert "ritual" in brief
    assert any("Do not load" in step or "do not skip" in step.lower() for step in brief["ritual"])
    text = " ".join(str(v) for v in brief.values()).lower()
    for banned in ("works because", "you should post", "recommend"):
        assert banned not in text


def test_brief_reports_evidence_coverage(peer):
    brief = pl.get_peer_library_brief("drleewarren")
    assert brief["coverage"]["transcripts"] == 60
    assert brief["coverage"]["components"] == 30
    assert brief["coverage"]["comment_analysis"] == 0


def test_comments_are_an_optional_drilldown(peer):
    result = pl.get_peer_comments("drleewarren", ["v000"])
    assert result["posts"][0]["available"] is False
    assert "not synced" in result["note"]


def test_empty_library_says_so(monkeypatch):
    monkeypatch.setattr(pl, "_all_rows", lambda account: [])
    monkeypatch.setattr(pl, "log_tool_call", lambda **kwargs: None)
    brief = pl.get_peer_library_brief("drleewarren")
    assert brief["catalog_size"] == 0
    assert "peer ingest" in brief["note"]


# -------------------------------------------------- shared helper behaviour ---


def test_rolling_stats_ignore_filtering_order():
    rows = _rows(n=80)
    forward = rolling_local_stats(rows)
    backward = rolling_local_stats(list(reversed(rows)))
    assert forward["v040"] == backward["v040"]


def test_rolling_median_excludes_the_focal_post():
    rows = [
        {
            "platform_post_id": str(index),
            "posted_at": f"2026-01-0{index + 1}T00:00:00+00:00",
            "metrics": {"views": views},
        }
        for index, views in enumerate([1, 2, 100, 3, 4])
    ]
    result = rolling_local_stats(rows, window=4, min_window=4)
    assert result["2"]["local_median_views"] == 2.5
    assert result["2"]["views_ratio"] == 40.0


def test_manifest_preserves_real_zero_ratios(peer):
    peer[0]["metrics"].update({"views": 100, "saves": 0, "comments": 0, "shares": 0})
    row = pl.get_peer_corpus_manifest(
        "drleewarren", video_ids=["v000"], limit=1
    )["posts"][0]
    assert row["saves_per_1k_views"] == 0.0
    assert row["comments_per_1k_views"] == 0.0
    assert row["shares_per_1k_views"] == 0.0


def test_cadence_handles_unparseable_dates():
    rows = [
        {"platform_post_id": "a", "posted_at": None, "metrics": {}},
        {"platform_post_id": "b", "posted_at": "not-a-date", "metrics": {}},
    ]
    out = cadence_fields(rows)
    assert out["a"]["days_since_previous_post"] is None
    assert out["b"]["iso_week"] is None


# ------------------------------------------------- account scoping in SQL ---
# The regression: content_posts reads filtered on platform alone, capped at 500
# rows and ordered newest-first. With ~1,372 peer posts in the table, DocMap's
# ~70 posts could be pushed out of the window entirely, so every DocMap read
# silently returned peer data.


class _FakeQuery:
    def __init__(self, rows, log):
        self._rows = rows
        self._log = log
        self._filters = {}

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        self._filters[column] = value
        self._log.append((column, value))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        rows = [
            r
            for r in self._rows
            if all(r.get(c) == v for c, v in self._filters.items())
        ]

        if hasattr(self, "_range"):
            start, end = self._range
            selected = rows[start : end + 1]
        else:
            selected = rows[: getattr(self, "_limit", len(rows))]

        class _R:
            data = selected

        return _R()


class _FakeClient:
    def __init__(self, rows, log):
        self._rows = rows
        self._log = log

    def table(self, _name):
        return _FakeQuery(self._rows, self._log)


def _mixed_rows():
    docmap = [
        {
            "platform": "tiktok",
            "account_handle": "docmap",
            "platform_post_id": f"d{i}",
            "posted_at": "2024-01-01T00:00:00+00:00",
            "metrics": {"views": 1000},
            "metadata": {},
        }
        for i in range(70)
    ]
    peer = [
        {
            "platform": "tiktok",
            "account_handle": "drleewarren",
            "platform_post_id": f"p{i}",
            "posted_at": "2026-01-01T00:00:00+00:00",
            "metrics": {"views": 90000},
            "metadata": {},
        }
        for i in range(1372)
    ]
    return peer + docmap


def test_docmap_reads_exclude_peer_rows(monkeypatch):
    import tools.tiktok_shared as ts

    log: list = []
    rows = _mixed_rows()
    monkeypatch.setattr(ts, "get_client", lambda: _FakeClient(rows, log))
    monkeypatch.setattr(ts, "_ACCOUNT_COLUMN_AVAILABLE", True)

    result = ts.fetch_tiktok_posts()
    assert ("account_handle", "docmap") in log
    assert len(result) == 70
    assert all(r["account_handle"] == "docmap" for r in result)


def test_scoped_read_rejects_mislabeled_returned_rows():
    import tools.tiktok_shared as ts

    with pytest.raises(RuntimeError, match="refusing mixed output"):
        ts._validate_account_rows(
            [{"platform_post_id": "peer-1", "account_handle": "drleewarren"}],
            "docmap",
        )


def test_peer_volume_cannot_displace_docmap(monkeypatch):
    """Without the SQL filter, 1,372 newer peer rows fill the 500-row window."""
    import tools.tiktok_shared as ts

    rows = _mixed_rows()
    monkeypatch.setattr(ts, "get_client", lambda: _FakeClient(rows, []))
    monkeypatch.setattr(ts, "_ACCOUNT_COLUMN_AVAILABLE", True)

    unscoped = ts.fetch_tiktok_posts(account=None)
    assert not any(r["account_handle"] == "docmap" for r in unscoped[:500])

    scoped = ts.fetch_tiktok_posts()
    assert len(scoped) == 70


def test_large_peer_read_is_paginated(monkeypatch):
    import tools.tiktok_shared as ts

    rows = _mixed_rows()
    monkeypatch.setattr(ts, "get_client", lambda: _FakeClient(rows, []))
    monkeypatch.setattr(ts, "_ACCOUNT_COLUMN_AVAILABLE", True)

    scoped = ts.fetch_tiktok_posts(limit=5000, account="drleewarren")
    assert len(scoped) == 1372


def test_single_video_read_is_scoped(monkeypatch):
    import tools.tiktok_shared as ts

    log: list = []
    rows = _mixed_rows()
    monkeypatch.setattr(ts, "get_client", lambda: _FakeClient(rows, log))
    monkeypatch.setattr(ts, "_ACCOUNT_COLUMN_AVAILABLE", True)

    assert ts.fetch_tiktok_post("p5") is None, "a peer id must not resolve for docmap"
    assert ts.fetch_tiktok_post("p5", account="drleewarren") is not None
    assert ts.fetch_tiktok_post("d5") is not None


def test_missing_column_fails_closed(monkeypatch):
    """A pre-migration database must never return a mixed library."""
    import tools.tiktok_shared as ts

    class _Raising(_FakeClient):
        def table(self, _name):
            q = _FakeQuery(self._rows, self._log)
            original = q.eq

            def eq(column, value):
                if column == "account_handle":
                    raise RuntimeError(
                        'column content_posts.account_handle does not exist'
                    )
                return original(column, value)

            q.eq = eq
            return q

    monkeypatch.setattr(ts, "get_client", lambda: _Raising(_mixed_rows(), []))
    monkeypatch.setattr(ts, "_ACCOUNT_COLUMN_AVAILABLE", True)

    with pytest.raises(RuntimeError, match="013_peer_libraries"):
        ts.fetch_tiktok_posts()
    assert ts.account_scope_enforced() is False
    monkeypatch.setattr(ts, "_ACCOUNT_COLUMN_AVAILABLE", True)


def test_corpus_ceiling_is_announced(monkeypatch):
    """Rolling medians are only valid over the whole catalog, so a truncated
    read must say so rather than quietly returning wrong ratios."""
    # Lower the ceiling rather than build 5,000 rows: era detection is O(n^2).
    monkeypatch.setattr(pl, "MAX_CORPUS_ROWS", 120)
    rows = _rows(n=120)
    monkeypatch.setattr(pl, "_all_rows", lambda account: rows)
    monkeypatch.setattr(pl, "log_tool_call", lambda **kwargs: None)

    manifest = pl.get_peer_corpus_manifest("drleewarren", limit=5)
    assert manifest["corpus_truncated"] is True
    assert "UNRELIABLE" in manifest["corpus_truncation_warning"]

    brief = pl.get_peer_library_brief("drleewarren")
    assert brief["corpus_truncated"] is True


def test_normal_catalog_is_not_flagged(peer):
    manifest = pl.get_peer_corpus_manifest("drleewarren", limit=5)
    assert manifest["corpus_truncated"] is False
    assert manifest["corpus_truncation_warning"] is None
