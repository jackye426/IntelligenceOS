"""Isolation guarantees for peer libraries.

Each test here covers a path that, before this work, would have corrupted or
deleted DocMap data on the first peer sync.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from marketing_pipeline import config
from marketing_pipeline.shared import embeddings
from marketing_pipeline.tiktok.stages import comment_labels
from marketing_pipeline.tiktok.stages.extract_components import (
    DEFAULT_SCHEMA,
    PEER_SCHEMA,
    prompt_fingerprint,
    resolve_schema,
)
from marketing_pipeline.tiktok.stages.fetch_catalog import entry_to_row
from marketing_pipeline.tiktok.sync import supabase as sync


@pytest.fixture(autouse=True)
def _restore_account():
    """Every test leaves the process pointed back at DocMap."""
    yield
    config.activate_account("docmap")


def test_docmap_activation_keeps_data_root():
    docmap_root = Path(config.DOCMAP_DATA_ROOT)
    config.activate_account("docmap")
    assert Path(config.DATA_ROOT) == docmap_root
    assert config.ACCOUNT == "docmap"
    assert config.is_peer_account() is False
    assert config.owner_scope() == "docmap"


def test_peer_activation_moves_every_path_off_the_docmap_tree(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETING_PEER_DATA_DIR", str(tmp_path / "peers"))
    config.activate_account("drleewarren")

    docmap_root = Path(config.DOCMAP_DATA_ROOT).resolve()
    for name, _leaf in config._DATA_ROOT_DERIVED:
        path = Path(getattr(config, name)).resolve()
        assert docmap_root not in path.parents, f"{name} still under the DocMap tree"
    assert Path(config.DATASET_JSON).resolve().parents[1] != docmap_root
    assert config.owner_scope() == "peer:drleewarren"
    assert config.is_peer_account() is True


def test_peer_resolving_onto_docmap_root_is_a_hard_error(monkeypatch):
    monkeypatch.setenv(
        "MARKETING_PEER_DATA_DIR_DRLEEWARREN", str(config.DOCMAP_DATA_ROOT)
    )
    with pytest.raises(config.AccountIsolationError):
        config.activate_account("drleewarren")


def test_urls_and_filenames_follow_the_account(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETING_PEER_DATA_DIR", str(tmp_path / "peer"))
    config.activate_account("drleewarren")
    assert config.profile_url() == "https://www.tiktok.com/@drleewarren"
    assert config.video_url("123") == "https://www.tiktok.com/@drleewarren/video/123"
    assert config.catalog_filename("2019-01-01") == "drleewarren_catalog_since_20190101.json"
    assert config.catalog_glob() == "drleewarren_catalog_since_*.json"


def test_catalog_rows_never_wear_the_wrong_handle(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETING_PEER_DATA_DIR", str(tmp_path / "peer"))
    config.activate_account("drleewarren")
    row = entry_to_row({"id": "999", "timestamp": 1713571200, "title": "t"})
    assert "@drleewarren/" in row["url"]
    assert "@docmap" not in row["url"]


def test_missing_metrics_are_null_not_blank_or_zero():
    row = entry_to_row({"id": "1", "timestamp": 1713571200})
    for field in ("view_count", "like_count", "save_count", "share_count", "duration_sec"):
        assert row[field] is None, f"{field} should be null when absent"
    populated = entry_to_row({"id": "1", "timestamp": 1713571200, "view_count": 0})
    assert populated["view_count"] == 0, "a real zero must survive"


def test_prune_refuses_to_run_without_an_account():
    with pytest.raises(ValueError, match="account is required"):
        sync._prune_stale_tiktok({"a"}, account="")


def test_prune_signature_requires_account_keyword():
    params = inspect.signature(sync._prune_stale_tiktok).parameters
    assert "account" in params
    assert params["account"].kind is inspect.Parameter.KEYWORD_ONLY


def test_orphan_embedding_prune_requires_owner_scope():
    with pytest.raises(ValueError, match="owner_scope is required"):
        embeddings.delete_orphan_tiktok_embeddings(
            post_ids=set(), comment_entity_ids=set(), video_ids=set(), owner_scope=""
        )


def test_embedding_writes_accept_an_owner_scope():
    params = inspect.signature(embeddings.upsert_embedding_chunks).parameters
    assert params["owner_scope"].default == "docmap"


def test_post_payloads_stamp_account_and_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETING_PEER_DATA_DIR", str(tmp_path / "peer"))
    config.activate_account("drleewarren")
    payload = sync._catalog_stub_payload("42", {"description": "hello", "url": None})
    assert payload["account_handle"] == "drleewarren"
    assert payload["owner_scope"] == "peer:drleewarren"
    assert "@drleewarren/" in payload["post_url"]


def test_component_schema_switches_with_the_account(tmp_path, monkeypatch):
    assert resolve_schema()[0] == DEFAULT_SCHEMA
    monkeypatch.setenv("MARKETING_PEER_DATA_DIR", str(tmp_path / "peer"))
    config.activate_account("drleewarren")
    name, prompt = resolve_schema()
    assert name == PEER_SCHEMA
    assert "endometriosis" not in prompt.lower()
    assert "any specialty" in prompt.lower()


def test_prompt_change_invalidates_cached_component_cards():
    from marketing_pipeline.tiktok.stages.extract_components import (
        DOCMAP_PROMPT,
        GENERIC_CLINICIAN_PROMPT,
        _inputs_hash,
    )

    common = {
        "transcript": "same words",
        "hook_detail": {"spoken_hook": "h"},
        "caption": "c",
        "duration_sec": 40,
    }
    a = _inputs_hash(
        **common, schema="docmap-endo", prompt_hash=prompt_fingerprint(DOCMAP_PROMPT)
    )
    b = _inputs_hash(
        **common,
        schema="generic-clinician",
        prompt_hash=prompt_fingerprint(GENERIC_CLINICIAN_PROMPT),
    )
    assert a != b, "identical inputs under a different prompt must miss the cache"


def test_comment_vocabulary_switches_with_the_account(tmp_path, monkeypatch):
    assert comment_labels.resolve_vocabulary()[0] == "docmap-endo"
    monkeypatch.setenv("MARKETING_PEER_DATA_DIR", str(tmp_path / "peer"))
    config.activate_account("drleewarren")
    assert comment_labels.resolve_vocabulary()[0] == "generic"


def test_generic_vocabulary_labels_a_non_endo_audience(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETING_PEER_DATA_DIR", str(tmp_path / "peer"))
    config.activate_account("drleewarren")
    texts = [
        "Where can I find your podcast?",
        "This helped me so much, thank you",
        "That is not true, show me a source",
        "I had a brain injury in 2019 and this made sense",
        "please make part 2",
    ]
    labels = [comment_labels.label_themes(t) for t in texts]
    assert all(ls != ["other_uncategorized"] for ls in labels)
    assert comment_labels.coverage(labels)["labelled_share"] == 1.0
    assert "asks_next_step" in labels[0]


def test_docmap_vocabulary_would_have_dropped_that_audience():
    """The regression the generic labeller exists to prevent."""
    texts = [
        "Where can I find your podcast?",
        "please make part 2",
    ]
    labels = [comment_labels.label_themes(t, vocabulary="docmap-endo") for t in texts]
    assert labels[1] == ["other_uncategorized"]


def test_peer_stats_use_the_catalog_not_the_network(tmp_path, monkeypatch):
    """A peer catalog already carries full metrics.

    Re-fetching them one video at a time added ~262 requests before any real
    work and was enough to get the client throttled mid-ingest.
    """
    from marketing_pipeline.tiktok.stages import refresh_stats as rs

    monkeypatch.setenv("MARKETING_PEER_DATA_DIR", str(tmp_path / "peer"))
    config.activate_account("drleewarren")

    def _boom(*_a, **_k):
        raise AssertionError("peer stats must not call yt-dlp")

    monkeypatch.setattr(rs, "fetch_yt_meta", _boom)

    catalog = [
        {
            "video_id": "1",
            "post_date_utc": "2024-01-01",
            "url": "u",
            "title": "t",
            "description": "d",
            "duration_sec": 60,
            "view_count": 1000,
            "like_count": 100,
            "comment_count": 10,
            "share_count": 5,
            "save_count": 20,
        }
    ]
    result = rs.refresh_stats(catalog, have_complete=set())
    assert result["count"] == 1

    written = json.loads((config.ANALYSIS_DIR / "metrics_refresh.json").read_text(encoding="utf-8"))
    row = written[0]
    assert row["source"] == "catalog"
    assert row["view_count"] == 1000
    assert row["save_per_1k_views"] == 20.0


def test_docmap_stats_still_refresh_from_the_network(tmp_path, monkeypatch):
    """The owned account keeps the live refresh: its stats do go stale."""
    from marketing_pipeline.tiktok.stages import refresh_stats as rs

    config.activate_account("docmap")
    calls = {"n": 0}

    def _meta(video_id, **_k):
        calls["n"] += 1
        return {"id": video_id, "view_count": 5, "duration": 10}

    monkeypatch.setattr(rs, "fetch_yt_meta", _meta)
    monkeypatch.setattr(rs.config, "ANALYSIS_DIR", tmp_path)
    rs.refresh_stats([{"video_id": "9"}], have_complete=set())
    assert calls["n"] == 1


def test_topic_gate_does_not_discard_peer_transcripts(tmp_path, monkeypatch):
    """The DocMap relevance gate must not run on another creator's speech.

    Regression: a neurosurgeon's caption trips the medical keyword list, his
    speech does not, and a perfectly good talking-head transcript was thrown
    away. This silently discarded ~half of a live peer ingest.
    """
    from marketing_pipeline.tiktok.stages.transcript_utils import is_garbage_transcript

    caption = "I'm a neurosurgeon, and here is why your pain is not the whole story."
    speech = "Hopelessness is deadly. Hope is life giving. Here is how you rewire it."

    config.activate_account("docmap")
    assert is_garbage_transcript(speech, caption_hint=caption) is True

    monkeypatch.setenv("MARKETING_PEER_DATA_DIR", str(tmp_path / "peer"))
    config.activate_account("drleewarren")
    assert is_garbage_transcript(speech, caption_hint=caption) is False


def test_generic_garbage_rules_still_apply_to_peers(tmp_path, monkeypatch):
    """Only the topic gate is account-scoped; real noise is still filtered."""
    from marketing_pipeline.tiktok.stages.transcript_utils import is_garbage_transcript

    monkeypatch.setenv("MARKETING_PEER_DATA_DIR", str(tmp_path / "peer"))
    config.activate_account("drleewarren")
    assert is_garbage_transcript("") is True
    assert is_garbage_transcript("music music music") is True
    assert is_garbage_transcript("   ") is True
    assert is_garbage_transcript("thanks for watching, see you in the next one") is True
    assert is_garbage_transcript("Your brain rewires around what you rehearse daily.") is False


def test_download_requests_a_format_that_has_audio(monkeypatch):
    """Regression: `-f best` picked TikTok's 1080p HEVC video-only rendition.

    Whisper then died inside PyAV with "tuple index out of range", which looks
    like a library bug rather than a missing audio track, and 16 downloads were
    silently useless.
    """
    import subprocess

    from marketing_pipeline.tiktok.stages import download_media as dm

    captured = {}

    def fake_check_call(cmd, **_k):
        captured["cmd"] = cmd
        return 0

    # None first (nothing cached), then a path once the download "ran".
    seen = {"n": 0}

    def fake_resolve(vid):
        seen["n"] += 1
        return None if seen["n"] == 1 else Path(f"{vid}.mp4")

    monkeypatch.setattr(subprocess, "check_call", fake_check_call)
    monkeypatch.setattr(dm, "resolve_media_path", fake_resolve)
    monkeypatch.setattr(dm, "has_audio_stream", lambda p: True)

    dm.download_media("123", dest_dir=Path("."))
    fmt = captured["cmd"][captured["cmd"].index("-f") + 1]
    assert fmt != "best", "plain 'best' selects a video-only rendition"
    assert "acodec!=none" in fmt


def test_download_rejects_a_video_only_result(monkeypatch, tmp_path):
    """A silent no-audio download must fail loudly, not reach Whisper."""
    import subprocess

    from marketing_pipeline.tiktok.stages import download_media as dm

    seen = {"n": 0}

    def fake_resolve(vid):
        seen["n"] += 1
        return None if seen["n"] == 1 else tmp_path / f"{vid}.mp4"

    monkeypatch.setattr(subprocess, "check_call", lambda *_a, **_k: 0)
    monkeypatch.setattr(dm, "resolve_media_path", fake_resolve)
    monkeypatch.setattr(dm, "has_audio_stream", lambda p: False)

    with pytest.raises(RuntimeError, match="no audio stream"):
        dm.download_media("123", dest_dir=tmp_path)


def test_master_transcripts_use_catalog_metrics_for_peers(tmp_path, monkeypatch):
    """Regression: refresh_metrics=True forced one yt-dlp call per transcript.

    On a 260-post peer library that is hundreds of requests fired straight after
    transcription; the failures were swallowed into empty dicts, which also
    silently destroyed the newest-first ordering of the master file.
    """
    from marketing_pipeline.tiktok.stages import write_master_transcripts as wmt

    monkeypatch.setenv("MARKETING_PEER_DATA_DIR", str(tmp_path / "peer"))
    config.activate_account("drleewarren")

    def _boom(*_a, **_k):
        raise AssertionError("peer master transcripts must not call yt-dlp")

    monkeypatch.setattr(wmt, "fetch_yt_meta", _boom)
    monkeypatch.setattr(
        wmt,
        "load_catalog",
        lambda _d: {
            "aaa": {
                "post_datetime_utc": "2026-08-03T12:00:00+00:00",
                "post_date_utc": "2026-08-03",
                "view_count": 500,
                "duration_sec": 60,
            }
        },
    )

    trans = config.TRANSCRIPTS_DIR
    trans.mkdir(parents=True, exist_ok=True)
    (trans / "aaa_COMPLETE.txt").write_text(
        "video_id: aaa\ntranscript:\nspoken words\n", encoding="utf-8"
    )

    out = wmt.write_master_transcripts(out_path=trans / "MASTER.txt", include_comments=False)
    assert out
    body = (trans / "MASTER.txt").read_text(encoding="utf-8")
    assert "spoken words" in body


def test_no_auto_ab_pairs_for_peers(tmp_path, monkeypatch):
    """An auto-detected A/B pair claims the creator ran an experiment.

    For an observed peer that is our inference, not their behaviour, so it must
    not appear in the dataset. It was also the slowest step in the pipeline: the
    comparison is O(n^2), and on 244 videos it spun for ~25 minutes.
    """
    from marketing_pipeline.tiktok.models import (
        TikTokHook,
        TikTokMarketingDataset,
        TikTokMetrics,
        TikTokPost,
        TikTokTranscript,
        TikTokVideoRecord,
    )
    from marketing_pipeline.tiktok.stages.detect_ab_pairs import detect_ab_pairs

    def _rec(vid, day):
        return TikTokVideoRecord(
            post=TikTokPost(
                video_id=vid,
                url="u",
                posted_at=f"2026-01-{day:02d}T00:00:00+00:00",
                metrics=TikTokMetrics(views=100, saves=1),
            ),
            transcript=TikTokTranscript(video_id=vid, full_text="identical spoken words here"),
            hook=TikTokHook(video_id=vid, onscreen_hook=f"hook {vid}"),
        )

    ds = TikTokMarketingDataset(videos={"a": _rec("a", 1), "b": _rec("b", 2)})

    monkeypatch.setenv("MARKETING_PEER_DATA_DIR", str(tmp_path / "peer"))
    config.activate_account("drleewarren")
    assert detect_ab_pairs(ds) == []


def test_component_store_paths_follow_the_active_account(tmp_path, monkeypatch):
    """Regression: the store froze its paths at import time.

    cli.py imports the orchestrator (and so this module) BEFORE activating the
    account, so the module constants bound to DocMap's tree and a peer run wrote
    its component cards straight into the owned library. One card actually
    leaked during the live ingest before this was caught.
    """
    from marketing_pipeline.tiktok.stages import video_components_store as store

    config.activate_account("docmap")
    docmap_dir = store.components_dir()
    assert "peers" not in str(docmap_dir)

    monkeypatch.setenv("MARKETING_PEER_DATA_DIR", str(tmp_path / "peer"))
    config.activate_account("drleewarren")
    peer_dir = store.components_dir()
    docmap_root = Path(config.DOCMAP_DATA_ROOT).resolve()
    assert peer_dir != docmap_dir
    assert docmap_root not in Path(peer_dir).resolve().parents
    assert Path(tmp_path) in Path(peer_dir).resolve().parents
    assert docmap_root not in Path(store.index_path()).resolve().parents


def test_component_cards_record_their_provenance():
    """A card on disk must say which account and prompt produced it."""
    from marketing_pipeline.tiktok.stages.video_components_models import ExtractionMeta

    meta = ExtractionMeta(
        account_handle="drleewarren",
        schema_version="generic-clinician",
        prompt_fingerprint="abc123",
    )
    dumped = meta.model_dump()
    assert dumped["account_handle"] == "drleewarren"
    assert dumped["schema_version"] == "generic-clinician"
    assert dumped["prompt_fingerprint"] == "abc123"
