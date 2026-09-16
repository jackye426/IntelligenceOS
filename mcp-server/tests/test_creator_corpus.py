"""MCP corpus tools: pagination, compare cap, playbook without transcripts."""

from __future__ import annotations

import json

import pytest

from tools import creator_corpus as cc
from tools.corpus_store import MemoryCorpus, set_corpus
from tools.tiktok_shared import DEFAULT_ACCOUNT


@pytest.fixture
def corpus():
    store = MemoryCorpus()
    set_corpus(store)
    yield store
    set_corpus(None)


def _profile(store: MemoryCorpus, handle: str, **extra):
    row = {
        "tiktok_user_id": handle,
        "handle": handle,
        "stage": "scored",
        "lane": "research",
        "specialty_key": "colorectal",
        "geo_country": "GB",
        "follower_count": 9000,
        "posts_30d": 8,
        "median_saves_per_1k": 12,
        "research_score": 70,
        "customer_score": 40,
        "is_doctor": True,
        "good_fit": True,
        "deep_status": "queued",
        "practice_setting": "private",
        "positioning_line": "bowel-prep clarity",
        "review_status": "pending",
    }
    row.update(extra)
    return store.insert("creator_profiles", row)


def test_list_creators_paginates_lean_rows(corpus):
    for i in range(3):
        _profile(corpus, f"dr{i}", research_score=50 + i)
    page = cc.list_creators(lane="research", order="research_score", cursor=0, limit=2)
    assert page["total_rows"] == 3
    assert page["returned_rows"] == 2
    assert page["next_cursor"] == 2
    dumped = json.dumps(page)
    assert "caption" not in dumped
    assert "transcript" not in dumped
    rest = cc.list_creators(lane="research", order="research_score", cursor=2, limit=2)
    assert rest["returned_rows"] == 1
    assert rest["next_cursor"] is None


def test_mcp_compare_rejects_more_than_eight(corpus):
    handles = [f"dr{i}" for i in range(9)]
    for handle in handles:
        _profile(corpus, handle)
    with pytest.raises(cc.CorpusError, match="at most 8"):
        cc.compare_creators(handles)
    six = cc.compare_creators(handles[:6])
    assert six["returned_rows"] == 6
    assert "transcript" not in json.dumps(six)


def test_mcp_playbook_does_not_inline_transcripts(corpus):
    _profile(corpus, "drjane")
    corpus.insert(
        "creator_specialty_stats",
        {
            "specialty_key": "colorectal",
            "n_doctors": 1,
            "exemplar_handles": {"high_saves": ["drjane"], "uk_private": ["drjane"]},
            "hook_job_histogram": {"name_the_problem": 4},
            "format_histogram": {"talking_head": 4},
            "cta_histogram": {"book_consult": 2},
        },
    )
    corpus.insert(
        "creator_peer_briefs",
        {
            "creator_profile_id": corpus.get("creator_profiles", handle="drjane")["id"],
            "account_handle": "drjane",
            "status": "confirmed",
            "schema_version": "content_guidelines_v1",
            "artefact": {
                "schema_version": "content_guidelines_v1",
                "sections": {
                    "0": {"title": "one_line_thesis", "body": "who it is about"},
                    "1": {"title": "first_15_seconds", "transcript": "SPOKEN_SECRET_WORDS"},
                    "2": {"beats": ["problem"]},
                    "5": {"caption_spec": "short"},
                    "9": {"anti_patterns": []},
                    "11": {"items": ["open on you"]},
                },
            },
        },
    )
    playbook = cc.get_specialty_playbook("colorectal")
    dumped = json.dumps(playbook)
    assert "SPOKEN_SECRET_WORDS" not in dumped
    assert playbook["cited_guidelines"][0]["guidelines"]["sections"]["0"]["body"] == "who it is about"
    assert "transcript" not in json.dumps(playbook["cited_guidelines"])


def test_review_creator_requires_confirmed(corpus):
    _profile(corpus, "drjane")
    preview = cc.review_creator("drjane", review_status="confirmed", confirmed=False)
    assert preview["preview"] is True
    kept = corpus.get("creator_profiles", handle="drjane")
    assert kept["review_status"] == "pending"
    written = cc.review_creator("drjane", review_status="confirmed", confirmed=True)
    assert written["written"] is True
    assert corpus.get("creator_profiles", handle="drjane")["review_status"] == "confirmed"


def test_get_tiktok_tools_default_docmap():
    assert DEFAULT_ACCOUNT == "docmap"
