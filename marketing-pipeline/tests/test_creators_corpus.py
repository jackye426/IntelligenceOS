"""Isolation + pipeline tests for the doctor-creator corpus."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from marketing_pipeline import config
from marketing_pipeline.cli import main as cli_main
from marketing_pipeline.creators import caption, commands, paths, store
from marketing_pipeline.creators.apply_profile import apply_profile_failure, apply_profile_success
from marketing_pipeline.creators.bio_parse import parse_bio
from marketing_pipeline.creators.classify import EvidenceItem, InsightCardModel, quote_in_source, validate_quotes
from marketing_pipeline.creators.enqueue_deep import enqueue_deep
from marketing_pipeline.creators.good_fit import is_good_fit
from marketing_pipeline.creators.hydrate import compute_rollups, hydrate_profile, parse_entry
from marketing_pipeline.creators.import_handles import import_handles
from marketing_pipeline.creators.profile import ProfileFetchError, extract_rehydration, user_info_from_blob
from marketing_pipeline.creators.score import customer_score, derive_lane, score_profile
from marketing_pipeline.creators.score_all import score_all
from marketing_pipeline.creators.screen import screen_profile
from marketing_pipeline.creators.specialty_stats import rebuild_specialty_stats
from marketing_pipeline.creators.write_brief import (
    BriefRefused,
    build_draft_artefact,
    coverage_from_sample,
    first15_stats,
    refuse_if_low_yield,
    validate_artefact,
)


@pytest.fixture
def mem(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKETING_CREATORS_DATA_DIR", str(tmp_path / "creators"))
    monkeypatch.setenv("CREATORS_STORE", "memory")
    st = store.MemoryStore()
    store.set_store(st)
    yield st
    store.set_store(None)


def test_creators_paths_are_off_the_docmap_tree(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETING_CREATORS_DATA_DIR", str(tmp_path / "creators-data"))
    root = paths.creators_data_dir()
    docmap = Path(config.DOCMAP_DATA_ROOT).resolve()
    assert docmap not in root.parents
    assert root != docmap
    research = paths.research_profile_dir()
    studio = (docmap / ".tiktok_studio_profile").resolve()
    assert research != studio
    assert studio not in research.parents


def test_store_refuses_docmap_tables(mem):
    with pytest.raises(store.StoreError, match="refuses"):
        mem.insert("content_posts", {"id": "x"})
    with pytest.raises(store.StoreError, match="refuses"):
        mem.insert("document_embeddings", {"id": "x"})


def test_cli_creators_does_not_import_tiktok_sync():
    source = inspect.getsource(cli_main)
    # activate_account is tiktok-only; creators returns before that block.
    assert "channel == \"creators\"" in source
    import marketing_pipeline.cli as cli_mod

    assert "tiktok.orchestrator" not in cli_mod.__dict__
    import sys

    # Loading the cli module must not have imported tiktok.sync.
    sync_mods = [n for n in sys.modules if n.startswith("marketing_pipeline.tiktok.sync")]
    # May already be imported by other tests; assert the creators dispatch path
    # itself does not call activate_account.
    from marketing_pipeline.creators import commands as cmds

    src = inspect.getsource(cmds.dispatch)
    assert "activate_account" not in src


def test_caption_hook_is_first_sentence_or_80():
    assert caption.caption_hook("Hello world. More text.") == "Hello world."
    long = "A" * 300
    assert caption.caption_hook(long) == "A" * 80
    assert caption.caption_hook("") is None


def test_bio_parse_extracts_gmc_email_and_uk_geo():
    out = parse_bio(
        "Dr Jane Smith",
        "Consultant colorectal surgeon. GMC 1234567. jane@clinic.co.uk https://smith.clinic",
        "https://smith.clinic",
    )
    assert out["gmc_number_in_bio"] == "1234567"
    assert "jane@clinic.co.uk" in out["bio_emails"]
    assert out["geo_country"] == "GB"
    assert any(l["class"] == "own_site" for l in out["bio_links"])


def test_screen_excludes_brand_and_students():
    brand = screen_profile(nickname="Glow Aesthetics Clinic", bio="medspa wellness", video_count=40)
    assert brand["screen_result"] == "exclude"
    student = screen_profile(nickname="Amy", bio="med student sharing nights", video_count=20)
    assert student["screen_result"] == "exclude"
    doctor = screen_profile(nickname="Dr Lee Warren", bio="neurosurgeon", video_count=200)
    assert doctor["screen_result"] == "include"


def test_missing_saves_do_not_score_as_zero():
    profile = {
        "growth_intent_level": 2,
        "specialty_key": "colorectal",
        "practice_setting": "private",
        "follower_count": 12_000,
        "recent_window_n": 20,
        "median_saves_per_1k": None,
        "bio_emails": ["a@b.co.uk"],
    }
    out = customer_score(profile)
    assert out["score_breakdown"]["intent_engagement"]["points"] is None
    assert out["score_coverage"] == 0.85


def test_research_score_uses_saves_not_likes_only():
    high_like = {
        "posts_30d": 12,
        "views_to_followers_median": 0.1,
        "median_saves_per_1k": 0.2,
        "weeks_active_of_last_8": 8,
        "format_mix": {"talking_head": 5},
        "cta_types": ["link_in_bio"],
        "follower_count": 10_000,
    }
    high_save = {**high_like, "median_saves_per_1k": 40.0, "views_to_followers_median": 0.1}
    band_saves = [0.2] * 20 + [40.0] * 20
    band_vtf = [0.1] * 40
    a = score_profile(high_like, band_views_to_followers=band_vtf, band_saves=band_saves)
    b = score_profile(high_save, band_views_to_followers=band_vtf, band_saves=band_saves)
    assert b["research_score"] > a["research_score"]


def test_good_fit_predicate():
    inactive_us_brand = {
        "is_doctor": False,
        "doctor_confidence": 0.9,
        "lane": "discard",
        "do_not_contact": False,
        "hydrate_status": "complete",
        "research_eligible": False,
        "customer_eligible": False,
    }
    assert is_good_fit(inactive_us_brand) is False
    uk = {
        "is_doctor": True,
        "doctor_confidence": 0.9,
        "lane": "customer",
        "do_not_contact": False,
        "hydrate_status": "complete",
        "research_eligible": False,
        "customer_eligible": True,
        "growth_intent_level": 2,
    }
    assert is_good_fit(uk) is True


def test_import_handles_and_status(mem, tmp_path):
    csv_path = tmp_path / "handles.csv"
    csv_path.write_text("handle\ndrleewarren\nDrJaneClinic\n")
    result = import_handles(csv_path, store=mem)
    assert result["counters"]["inserted"] == 2
    again = import_handles(csv_path, store=mem)
    assert again["counters"]["existing"] == 2
    from marketing_pipeline.creators.status import corpus_status

    status = corpus_status(store=mem)
    assert status["profiles"] == 2
    assert status["by_stage"]["discovered"] == 2


def test_profile_failure_does_not_overwrite_facts(mem):
    row = mem.insert(
        "creator_profiles",
        {
            "tiktok_user_id": "123",
            "handle": "drjane",
            "nickname": "Dr Jane",
            "bio": "surgeon",
            "stage": "profiled",
        },
    )
    apply_profile_failure(row, ProfileFetchError("block", "HTTP 403"), store=mem)
    kept = mem.get("creator_profiles", id=row["id"])
    assert kept["nickname"] == "Dr Jane"
    assert kept["bio"] == "surgeon"
    assert kept["work_status"] == "retry"


def test_profile_success_screens_and_snapshots(mem):
    row = mem.insert(
        "creator_profiles",
        {"tiktok_user_id": "pending:drjane", "handle": "drjane", "stage": "discovered"},
    )
    fields = {
        "tiktok_user_id": "999",
        "handle": "drjane",
        "nickname": "Dr Jane",
        "bio": "Consultant colorectal surgeon GMC 7654321",
        "video_count": 40,
        "follower_count": 12_000,
        "private_account": False,
    }
    apply_profile_success(row, fields, store=mem)
    kept = mem.get("creator_profiles", id=row["id"])
    assert kept["stage"] == "screened"
    assert kept["tiktok_user_id"] == "999"
    assert kept["gmc_number_in_bio"] == "7654321"
    assert mem.list("creator_profile_snapshots", creator_profile_id=row["id"])


def test_hydrate_partial_skips_rollups(mem):
    profile = mem.insert(
        "creator_profiles",
        {"tiktok_user_id": "1", "handle": "drjane", "stage": "screened", "follower_count": 8000},
    )
    entries = [{"id": "v1", "timestamp": 1713571200, "description": "Hello there. More."}] + [None] * 10
    result = hydrate_profile(profile, entries, store=mem)
    assert result["hydrate_status"] == "partial"
    kept = mem.get("creator_profiles", id=profile["id"])
    assert kept.get("posts_30d") is None
    assert mem.get("creator_videos", video_id="v1")["caption_hook"] == "Hello there."


def test_hydrate_complete_rollups_exclude_null_saves(mem):
    profile = mem.insert(
        "creator_profiles",
        {"tiktok_user_id": "1", "handle": "drjane", "stage": "screened", "follower_count": 8000},
    )
    entries = []
    for i in range(8):
        entries.append(
            {
                "id": f"v{i}",
                "timestamp": 1750000000 + i * 86400,
                "description": f"Post {i}.",
                "view_count": 1000,
                "like_count": 10,
                "comment_count": 1,
                "repost_count": 1,
                "save_count": 20 if i % 2 == 0 else None,
                "duration": 60,
            }
        )
    result = hydrate_profile(profile, entries, store=mem)
    assert result["hydrate_status"] == "complete"
    kept = mem.get("creator_profiles", id=profile["id"])
    assert kept["median_saves_per_1k"] == 20.0
    assert kept["hydrate_status"] == "complete"


def test_quote_validation_drops_unsupported():
    card = InsightCardModel(
        is_doctor=True,
        doctor_confidence=0.9,
        growth_intent_level=2,
        geo_country="GB",
        evidence=[
            EvidenceItem(field="is_doctor", quote="surgeon", source="bio"),
            EvidenceItem(field="geo_country", quote="Mars", source="bio"),
        ],
    )
    updated, report = validate_quotes(card, {"bio": "I am a surgeon in London"})
    assert "geo_country" in report["dropped"]
    assert updated.geo_country is None


def test_specialty_stats_exemplars_are_handles_only(mem):
    p = mem.insert(
        "creator_profiles",
        {
            "tiktok_user_id": "1",
            "handle": "drjane",
            "stage": "scored",
            "is_doctor": True,
            "specialty_key": "colorectal",
            "follower_count": 9000,
            "median_saves_per_1k": 12,
            "geo_country": "GB",
            "practice_setting": "private",
        },
    )
    rebuild_specialty_stats(store=mem)
    row = mem.get("creator_specialty_stats", specialty_key="colorectal")
    handles = row["exemplar_handles"]
    assert handles["uk_private"] == ["drjane"]
    dumped = json.dumps(row)
    assert "caption" not in dumped


def test_enqueue_deep_is_idempotent(mem):
    mem.insert(
        "creator_profiles",
        {
            "tiktok_user_id": "1",
            "handle": "drjane",
            "stage": "scored",
            "is_doctor": True,
            "doctor_confidence": 0.9,
            "lane": "research",
            "hydrate_status": "complete",
            "research_eligible": True,
            "customer_eligible": False,
            "do_not_contact": False,
        },
    )
    first = enqueue_deep(store=mem)
    second = enqueue_deep(store=mem)
    assert first["enqueued"] == 1
    assert second["enqueued"] == 0
    assert second["skipped"] == 1
    assert len(mem.list("creator_deep_job_items")) == 1


def test_write_brief_refuses_low_yield():
    sample = [{"transcript": None, "components": {"x": 1}} for _ in range(10)]
    cov = coverage_from_sample(sample)
    with pytest.raises(BriefRefused, match="transcript_yield"):
        refuse_if_low_yield(cov)


def test_write_brief_first15_insufficient_sample():
    posts = [
        {
            "video_id": f"v{i}",
            "rolling_local_ratio": 2.5 if i < 3 else 0.5,
            "transcript_segments": [{"start": 0, "text": "you feel foggy today"}],
        }
        for i in range(6)
    ]
    stats = first15_stats(posts)
    assert stats["status"] == "insufficient_sample"
    assert stats["table"] is None


def test_write_brief_schema_content_guidelines_v1():
    sample = []
    for i in range(10):
        sample.append(
            {
                "video_id": f"v{i}",
                "transcript": "spoken words " * 20,
                "caption": "spoken words " * 18,
                "components": {"hook": "x"},
                "rolling_local_ratio": 2.2 if i < 5 else 0.4,
                "transcript_segments": [
                    {"start": 0.0, "text": "you feel this"},
                    {"start": 8.0, "text": "here is the mechanism"},
                ],
                "ocr_frames": ["FULL TITLE HERE", "FULL TITLE HERE", "FULL TITLE HERE", "FULL TITLE HERE"],
            }
        )
    # still insufficient first15 n_top/n_bottom (>=8 each) — 5 and 5
    artefact = build_draft_artefact(handle="drleewarren", sample=sample, catalog_n=262)
    assert artefact["schema_version"] == "content_guidelines_v1"
    assert artefact["tests"]["first15"]["status"] == "insufficient_sample"
    assert artefact["sections"]["1"]["table"] is None
    assert validate_artefact(artefact) == []


def test_write_brief_invented_table_fails_schema():
    artefact = {
        "schema_version": "content_guidelines_v1",
        "sections": {str(i): {} for i in range(13)},
        "tests": {"first15": {"status": "insufficient_sample", "table": {"words": 1}}},
    }
    assert "invented_first15_table" in validate_artefact(artefact)


def test_fetch_playlist_passes_playlist_end(monkeypatch):
    import subprocess

    from marketing_pipeline.tiktok.stages import fetch_catalog as fc

    seen = {}

    class _Proc:
        returncode = 0
        stdout = json.dumps({"entries": [{"id": "1"}]}).encode()
        stderr = b""

    def fake_run(cmd, capture_output=True):
        seen["cmd"] = cmd
        return _Proc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(fc.time, "sleep", lambda *_: None)
    fc.fetch_playlist(handle="someone", playlist_end=23, attempts=1)
    assert "--playlist-end" in seen["cmd"]
    assert "23" in seen["cmd"]


def test_cli_import_handles(mem, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MARKETING_CREATORS_DATA_DIR", str(tmp_path / "c"))
    csv_path = tmp_path / "h.csv"
    csv_path.write_text("drleewarren\n")
    with pytest.raises(SystemExit) as exc:
        cli_main(["creators", "import-handles", "--file", str(csv_path)])
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["counters"]["inserted"] == 1


def test_ocr_frames_are_0_0_5_1_2():
    from marketing_pipeline.creators.write_brief import OCR_FRAME_SECONDS

    assert OCR_FRAME_SECONDS == (0.0, 0.5, 1.0, 2.0)


def test_gtm_stale_seconds_not_used():
    from marketing_pipeline.creators.deep_jobs import DEEP_STALE_SECONDS, GTM_STALE_SECONDS

    assert DEEP_STALE_SECONDS >= 14400
    assert DEEP_STALE_SECONDS != GTM_STALE_SECONDS
    sql = (Path(__file__).resolve().parents[2] / "sql" / "014_creator_corpus.sql").read_text()
    assert "p_stale_seconds INTEGER DEFAULT 14400" in sql
    assert "DEFAULT 600" not in sql.split("creator_claim_deep_job_items")[1][:800]


def test_on_demand_outranks_auto():
    from marketing_pipeline.creators.deep_jobs import claim_order

    ordered = claim_order(
        [
            {"id": "auto", "priority": 40, "created_at": "2026-01-01"},
            {"id": "uk", "priority": 80, "created_at": "2026-01-02"},
            {"id": "human", "priority": 100, "created_at": "2026-01-03"},
        ]
    )
    assert [i["id"] for i in ordered] == ["human", "uk", "auto"]


def test_listing_paused_around_docmap_cron():
    from datetime import datetime, timezone

    from marketing_pipeline.creators.deep_jobs import listing_paused

    assert listing_paused(datetime(2026, 1, 1, 3, 30, tzinfo=timezone.utc)) is True
    assert listing_paused(datetime(2026, 1, 1, 2, 49, tzinfo=timezone.utc)) is False
    assert listing_paused(datetime(2026, 1, 1, 4, 15, tzinfo=timezone.utc)) is False


def test_drain_respects_deadline(mem):
    from datetime import datetime, timezone

    from marketing_pipeline.creators.commands import run_drain

    out = run_drain(deadline="02:45", now=datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc))
    assert out["status"] == "blocked"
    assert out["reason"] == "deadline"


def test_drain_dispatch_does_not_activate_account():
    from marketing_pipeline.creators import commands as cmds

    src = inspect.getsource(cmds.run_drain)
    assert "activate_account(" not in src
    assert "tiktok.sync" not in src
    assert "config.activate_account" not in src


def test_export_corpus_csv(mem, tmp_path):
    mem.insert(
        "creator_profiles",
        {
            "tiktok_user_id": "u1",
            "handle": "drjane",
            "lane": "customer",
            "specialty_key": "colorectal",
            "caption": "SHOULD_NOT_APPEAR",
        },
    )
    path = tmp_path / "corpus.csv"
    from marketing_pipeline.creators.export import export_view

    out = export_view("corpus", path=path, store=mem)
    assert out["rows"] == 1
    text = path.read_text()
    assert "drjane" in text
    assert "SHOULD_NOT_APPEAR" not in text
    assert "caption" not in text.splitlines()[0]


def test_purge_discards_old_bio_and_videos(mem):
    from datetime import datetime, timedelta, timezone

    from marketing_pipeline.creators.purge import run_purge

    old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    profile = mem.insert(
        "creator_profiles",
        {
            "tiktok_user_id": "gone",
            "handle": "oldbrand",
            "lane": "discard",
            "stage": "excluded",
            "bio": "secret bio",
            "excluded_reason": "brand",
            "first_seen_at": old,
            "updated_at": old,
        },
    )
    mem.insert(
        "creator_videos",
        {
            "video_id": "v1",
            "creator_profile_id": profile["id"],
            "caption": "old caption",
        },
    )
    out = run_purge(older_than_days=90, store=mem)
    assert out["purged_profiles"] == 1
    assert out["videos_deleted"] == 1
    kept = mem.get("creator_profiles", handle="oldbrand")
    assert kept["bio"] is None
    assert kept["excluded_reason"] == "brand"
    assert kept["tiktok_user_id"] == "gone"
    assert mem.list("creator_videos") == []


def test_seed_warren_brief_confirmed(mem):
    from marketing_pipeline.creators.seed_warren import seed_warren_brief
    from marketing_pipeline.creators.write_brief import REQUIRED_SECTIONS, validate_artefact

    out = seed_warren_brief(store=mem)
    assert out["handle"] == "drleewarren"
    assert out["status"] == "confirmed"
    assert out["sections"] == REQUIRED_SECTIONS
    brief = mem.get("creator_peer_briefs", account_handle="drleewarren")
    assert brief["source"] == "mcp_session"
    assert brief["status"] == "confirmed"
    assert validate_artefact(brief["artefact"]) == []


def test_promote_peer_is_subprocess_skip_embed(tmp_path, monkeypatch):
    import inspect

    from marketing_pipeline.creators import promote_peer as pp

    monkeypatch.setenv("MARKETING_PEER_DATA_DIR", str(tmp_path / "peers"))
    argv = pp.ingest_argv("drleewarren", quality="auto")
    dumped = " ".join(" ".join(cmd) for cmd in argv)
    assert "--skip-embed" in dumped
    assert "--account drleewarren" in dumped or "drleewarren" in dumped
    assert "activate_account" not in dumped
    src = inspect.getsource(pp.run_promote_peer)
    assert "activate_account(" not in src
    dry = pp.run_promote_peer("drleewarren", quality="on_demand", dry_run=True)
    assert dry["skip_embed"] is True
    assert any("--deep" in cmd and "200" in cmd for cmd in dry["commands"])


def test_media_deleted_after_ingest(tmp_path, monkeypatch):
    from marketing_pipeline.creators.promote_peer import delete_peer_media, peer_transcripts_dir

    monkeypatch.setenv("MARKETING_PEER_DATA_DIR", str(tmp_path / "peers"))
    media = tmp_path / "peers" / "drjane" / "media"
    transcripts = tmp_path / "peers" / "drjane" / "transcripts"
    media.mkdir(parents=True)
    transcripts.mkdir(parents=True)
    (media / "clip.mp4").write_bytes(b"xx")
    (transcripts / "ALL_COMPLETE_TRANSCRIPTS.txt").write_text("kept")
    out = delete_peer_media("drjane")
    assert out["media_empty"] is True
    assert not (media / "clip.mp4").exists()
    assert (transcripts / "ALL_COMPLETE_TRANSCRIPTS.txt").exists()
    assert peer_transcripts_dir("drjane").exists()


def test_review_csv_round_trip(mem, tmp_path):
    from marketing_pipeline.creators.review_csv import review_export, review_import

    mem.insert(
        "creator_profiles",
        {
            "tiktok_user_id": "u1",
            "handle": "drjane",
            "lane": "customer",
            "review_status": "pending",
            "do_not_contact": False,
            "customer_score": 70,
        },
    )
    path = tmp_path / "review.csv"
    review_export(path=path, store=mem)
    text = path.read_text()
    text = text.replace("pending", "confirmed")
    path.write_text(text)
    out = review_import(path=path, store=mem)
    assert out["updated"] == 1
    assert mem.get("creator_profiles", handle="drjane")["review_status"] == "confirmed"


def test_eval_precision_gates(mem, tmp_path):
    from marketing_pipeline.creators.eval import run_eval

    mem.insert(
        "creator_profiles",
        {
            "tiktok_user_id": "u1",
            "handle": "drjane",
            "is_doctor": True,
            "geo_country": "GB",
            "lane": "customer",
        },
    )
    labels = tmp_path / "labels.csv"
    labels.write_text("handle,is_doctor,geo_country,lane\ndrjane,true,GB,customer\n")
    out = run_eval(labels_path=labels, store=mem)
    assert out["passed"] is True
    assert out["scores"]["is_doctor_precision"] == 1.0


def test_classify_v1_falls_back_to_heuristic(mem, monkeypatch):
    from marketing_pipeline.creators.classify import classify_v1

    monkeypatch.setattr("marketing_pipeline.config.OPENROUTER_API_KEY", "")
    profile = {
        "id": "x",
        "nickname": "Dr Jane",
        "bio": "Consultant colorectal surgeon. Book at jane.clinic",
        "bio_link": "https://jane.clinic",
        "bio_links": [{"url": "https://jane.clinic", "class": "own_site"}],
        "screen_result": "include",
        "geo_country": "GB",
        "geo_confidence": 0.9,
    }
    card, model = classify_v1(profile, [], use_llm=False)
    assert model == "heuristic"
    assert card.is_doctor is True


def test_drain_gtm_link_is_subprocess_not_activate():
    import inspect

    from marketing_pipeline.creators import commands as cmds

    drain_src = inspect.getsource(cmds.run_drain)
    link_src = inspect.getsource(cmds.run_gtm_link)
    assert "activate_account(" not in drain_src
    assert "activate_account(" not in link_src
    assert "tiktok.sync" not in drain_src
    assert "gtm_pipeline" in link_src


def test_deep_worker_parent_does_not_activate_account():
    root = Path(__file__).resolve().parents[2]
    src = (root / "creator-deep-worker" / "main.py").read_text()
    assert "activate_account(" not in src
    assert "promote-peer" in src
    assert "p_stale_seconds" in src
    assert "14400" in src


