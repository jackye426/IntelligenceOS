from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from peer_content_proof import ACCOUNTS, OPENING_SECONDS, evidence_status, run_proof


class Query:
    def __init__(self, rows, db):
        self.rows, self.db, self.patch = rows, db, None

    def eq(self, field, value):
        self.rows = [r for r in self.rows if r.get(field) == value]
        return self

    def select(self, _fields):
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    def update(self, patch):
        self.patch = patch
        return self

    def execute(self):
        if self.patch is not None:
            assert set(self.patch) == {"caption", "transcript", "metadata", "updated_at"}
            for row in self.rows:
                self.db.writes.append(row["id"])
                row.update(self.patch)
        return SimpleNamespace(data=self.rows)


class DB:
    def __init__(self, targets):
        self.writes = []
        captured = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        self.posts, self.owned, self.peers = [], [], []
        for account, video in targets.items():
            row = {
                "id": video, "platform_post_id": video,
                "account_handle": account, "platform": "tiktok",
                "owner_scope": f"peer:{account}",
                "post_url": f"https://www.tiktok.com/@{account}/video/{video}",
                "metadata": {"is_catalog_stub": True, "source": "yt_dlp"},
                "updated_at": captured,
            }
            self.posts.append(row)
            group = self.owned if account == "endobowelsurgeon" else self.peers
            group.append({**row, "captured_at": captured, "source": "yt_dlp", "metrics": {"views": 9}})

    def table(self, name):
        return Query({"content_posts": self.posts, "latest_social_metric_snapshots": self.owned,
                      "latest_public_tiktok_peer_metrics": self.peers}[name], self)


@pytest.fixture
def targets():
    return {account: str(10000 + i) for i, account in enumerate(ACCOUNTS)}


def evidence(url, account, video):
    assert url == f"https://www.tiktok.com/@{account}/video/{video}"
    return "A caption", [{"start": 0, "end": 1, "text": "speech"}], "speech", [
        {"second": second, "text": "existing visible text"} for second in OPENING_SECONDS
    ]


def test_dry_run_is_read_only_and_does_not_download(targets):
    db = DB(targets)

    def forbidden(*_):
        pytest.fail("dry run should not download")

    assert all(item["status"] == "ready" for item in run_proof(
        db, targets, collect=forbidden
    ).values())
    assert not db.writes


def test_proof_is_one_per_account_and_preserves_metrics_and_existing_metadata(targets):
    db = DB(targets)
    results = run_proof(db, targets, apply=True, collect=evidence)
    assert all(item["status"] == "stored" for item in results.values())
    assert set(db.writes) == set(targets.values())
    assert len(db.writes) == 3
    for post in db.posts:
        assert post["metadata"]["source"] == "yt_dlp"
        assert post["metadata"]["ocr_evidence"]["scope"] == "opening_frames"
        assert post["metadata"]["transcript_segments"][0]["start"] == 0


def test_stale_wrong_scope_and_wrong_source_are_not_collected(targets):
    db = DB(targets)
    db.owned[0]["captured_at"] = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    db.peers[0]["owner_scope"] = "docmap"
    db.peers[1]["source"] = "display_api"
    assert all(item["status"] == "failed" for item in run_proof(
        db, targets, apply=True, collect=lambda *_: pytest.fail("invalid scope or freshness")
    ).values())
    assert not db.writes


def test_canonical_url_required(targets):
    db = DB(targets)
    db.posts[0]["post_url"] = "https://example.com/untrusted"
    results = run_proof(db, targets, apply=True, collect=evidence)
    assert results["endobowelsurgeon"]["status"] == "failed"
    assert len(db.writes) == 2


def test_bulk_or_unknown_account_rejected(targets):
    with pytest.raises(ValueError):
        run_proof(DB(targets), {**targets, "extra": "12345"})


def test_retry_does_not_recollect_completed_evidence(targets):
    db = DB(targets)
    run_proof(db, targets, apply=True, collect=evidence)
    result = run_proof(db, targets, apply=True, collect=lambda *_: pytest.fail("recollect"))
    assert all(v["status"] == "already_stored" for v in result.values())
    assert len(db.writes) == 3


def test_conflicting_catalogue_update_is_not_overwritten(targets):
    db = DB(targets)

    def race(url, account, video):
        db.posts[0]["updated_at"] = datetime.now(timezone.utc).isoformat()
        return evidence(url, account, video)

    results = run_proof(db, targets, apply=True, collect=race)
    assert results["endobowelsurgeon"]["status"] == "failed"
    assert len(db.writes) == 2


def test_valid_silent_and_text_free_video_is_not_processing_failure(targets):
    db = DB(targets)
    blank = [{"second": second, "text": ""} for second in OPENING_SECONDS]
    valid_negative = run_proof(
        db, targets, apply=True, collect=lambda *_: ("A caption", [], "", blank)
    )
    for result in valid_negative.values():
        assert result["status"] == "failed"  # not a suitable proof clip
        assert result["transcript_evidence"] == "not_present"
        assert result["opening_ocr_evidence"] == "not_present"
    assert not db.writes
    assert evidence_status(processing_completed=False, content_present=False) == "processing_failed"


def test_partial_frame_processing_is_not_text_free(targets):
    db = DB(targets)
    partial = run_proof(
        db, targets, apply=True, collect=lambda *_: ("A caption", [], "", [])
    )
    assert all(result["opening_ocr_evidence"] == "processing_failed"
               for result in partial.values())
    assert not db.writes
