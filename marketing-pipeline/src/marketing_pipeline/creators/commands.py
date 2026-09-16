"""CLI command implementations for `python -m marketing_pipeline creators`."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from marketing_pipeline.creators.apply_profile import apply_profile_failure, apply_profile_success
from marketing_pipeline.creators.caption import caption_hook
from marketing_pipeline.creators.classify import apply_card, heuristic_card, input_hash
from marketing_pipeline.creators.enqueue_deep import enqueue_deep
from marketing_pipeline.creators.hydrate import hydrate_profile
from marketing_pipeline.creators.import_handles import import_handles
from marketing_pipeline.creators.paths import assert_isolated_from_docmap, normalise_handle
from marketing_pipeline.creators.profile import (
    ProfileFetchError,
    extract_rehydration,
    fetch_profile_html,
    profile_fields,
    user_info_from_blob,
)
from marketing_pipeline.creators.runs import exit_code, finish_run, start_run
from marketing_pipeline.creators.score_all import score_all
from marketing_pipeline.creators.status import corpus_status
from marketing_pipeline.creators.store import get_store
from marketing_pipeline.creators.specialty_stats import rebuild_specialty_stats
from marketing_pipeline.creators.write_brief import BriefRefused, build_draft_artefact


def run_status() -> dict[str, Any]:
    assert_isolated_from_docmap()
    return corpus_status()


def run_import_handles(path: Path) -> dict[str, Any]:
    assert_isolated_from_docmap()
    return import_handles(path)


def run_seed_import(path: Path) -> dict[str, Any]:
    assert_isolated_from_docmap()
    store = get_store()
    run = start_run("seed-import", params={"file": str(path)}, store=store)
    import csv

    n = 0
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            store.upsert(
                "creator_seeds",
                {
                    "slice": row.get("slice") or "manual",
                    "source_type": row.get("source_type") or "manual",
                    "value": row.get("value") or "",
                    "priority": int(row.get("priority") or 50),
                    "status": "active",
                    "meta": {},
                },
            )
            n += 1
    finish_run(run["id"], status="completed", counters={"seeds": n}, store=store)
    return {"run_id": run["id"], "status": "completed", "counters": {"seeds": n}}


def run_profile(*, handle: str | None = None, html: Path | None = None) -> dict[str, Any]:
    assert_isolated_from_docmap()
    store = get_store()
    run = start_run("profile", params={"handle": handle}, store=store)
    counters = {"ok": 0, "unavailable": 0, "blocked": 0, "failed": 0}
    profiles = store.list("creator_profiles", handle=normalise_handle(handle)) if handle else [
        p for p in store.list("creator_profiles") if p.get("stage") in {"discovered", "profiled"}
    ]
    for profile in profiles:
        try:
            raw = html.read_text(encoding="utf-8") if html else fetch_profile_html(profile["handle"])
            blob = extract_rehydration(raw)
            info = user_info_from_blob(blob)
            fields = profile_fields(info)
            apply_profile_success(profile, fields, store=store)
            counters["ok"] += 1
        except ProfileFetchError as exc:
            apply_profile_failure(profile, exc, store=store)
            counters[exc.kind if exc.kind in counters else "failed"] += 1
            if exc.kind == "block":
                finish_run(run["id"], status="blocked", counters=counters, error=str(exc), store=store)
                return {"run_id": run["id"], "status": "blocked", "counters": counters}
        except Exception as exc:  # noqa: BLE001
            counters["failed"] += 1
            store.update("creator_profiles", {"last_error": str(exc), "work_status": "retry"}, id=profile["id"])
    status = "completed" if counters["failed"] == 0 else "degraded"
    finish_run(run["id"], status=status, counters=counters, store=store)
    return {"run_id": run["id"], "status": status, "counters": counters}


def run_hydrate(*, handle: str | None = None, playlist_end: int = 23, fixture: Path | None = None) -> dict[str, Any]:
    assert_isolated_from_docmap()
    store = get_store()
    run = start_run("hydrate", params={"playlist_end": playlist_end}, store=store)
    counters = {"complete": 0, "partial": 0, "blocked": 0}
    if handle:
        profiles = [store.get("creator_profiles", handle=normalise_handle(handle))]
        profiles = [p for p in profiles if p]
    else:
        profiles = [p for p in store.list("creator_profiles") if p.get("stage") in {"screened", "hydrated"}]
    for profile in profiles:
        if fixture:
            entries = json.loads(fixture.read_text(encoding="utf-8"))
            if isinstance(entries, dict):
                entries = entries.get("entries") or []
        else:
            from marketing_pipeline.creators import ratelimit
            from marketing_pipeline.tiktok.stages.fetch_catalog import fetch_playlist

            ratelimit.LISTING.acquire()
            playlist = fetch_playlist(handle=profile["handle"], playlist_end=playlist_end)
            entries = playlist.get("entries") or []
        result = hydrate_profile(profile, entries, store=store)
        status = result.get("hydrate_status") or "complete"
        counters[status if status in counters else "complete"] = counters.get(status, 0) + 1
        if status == "blocked":
            finish_run(run["id"], status="blocked", counters=counters, store=store)
            return {"run_id": run["id"], "status": "blocked", "counters": counters}
    overall = "completed" if counters["partial"] == 0 else "degraded"
    finish_run(run["id"], status=overall, counters=counters, store=store)
    return {"run_id": run["id"], "status": overall, "counters": counters}


def run_classify(*, handle: str | None = None) -> dict[str, Any]:
    assert_isolated_from_docmap()
    store = get_store()
    run = start_run("classify", store=store)
    n = 0
    profiles = store.list("creator_profiles")
    if handle:
        profiles = [p for p in profiles if p.get("handle") == normalise_handle(handle)]
    for profile in profiles:
        if profile.get("stage") not in {"hydrated", "classified", "scored"}:
            continue
        if profile.get("screen_result") == "exclude":
            continue
        videos = store.list("creator_videos", creator_profile_id=profile["id"])
        payload = {
            "nickname": profile.get("nickname"),
            "bio": profile.get("bio"),
            "hooks": [v.get("caption_hook") for v in videos[:23]],
        }
        key = input_hash(payload)
        cached = store.get(
            "creator_insight_cards",
            creator_profile_id=profile["id"],
            classifier_version="classify_v1",
            input_hash=key,
        )
        if cached:
            n += 1
            continue
        card = heuristic_card(profile, videos)
        apply_card(profile, card, store=store, input_key=key)
        n += 1
    finish_run(run["id"], status="completed", counters={"classified": n}, store=store)
    return {"run_id": run["id"], "status": "completed", "counters": {"classified": n}}


def run_score() -> dict[str, Any]:
    assert_isolated_from_docmap()
    store = get_store()
    run = start_run("score", store=store)
    result = score_all(store=store)
    stats = rebuild_specialty_stats(store=store)
    finish_run(run["id"], status="completed", counters={**result, **stats}, store=store)
    return {"run_id": run["id"], "status": "completed", "counters": {**result, **stats}}


def run_rebuild_specialty_stats() -> dict[str, Any]:
    assert_isolated_from_docmap()
    return rebuild_specialty_stats()


def run_enqueue_deep() -> dict[str, Any]:
    assert_isolated_from_docmap()
    store = get_store()
    run = start_run("enqueue-deep", store=store)
    result = enqueue_deep(store=store)
    finish_run(run["id"], status="completed", counters=result, store=store)
    return {"run_id": run["id"], "status": "completed", "counters": result}


def run_write_brief(handle: str, *, sample_path: Path | None = None) -> dict[str, Any]:
    assert_isolated_from_docmap()
    store = get_store()
    run = start_run("write-brief", params={"handle": handle}, store=store)
    profile = store.get("creator_profiles", handle=normalise_handle(handle))
    if not profile:
        finish_run(run["id"], status="failed", error="unknown handle", store=store)
        return {"status": "failed", "error": "unknown handle"}
    if sample_path:
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
    else:
        sample = []
    try:
        artefact = build_draft_artefact(
            handle=profile["handle"],
            sample=sample,
            catalog_n=len(sample),
        )
    except BriefRefused as exc:
        store.update("creator_profiles", {"deep_status": "brief_failed"}, id=profile["id"])
        finish_run(run["id"], status="failed", error=exc.reason, counters=exc.coverage, store=store)
        return {"status": "failed", "reason": exc.reason, "coverage": exc.coverage}
    store.upsert(
        "creator_peer_briefs",
        {
            "creator_profile_id": profile["id"],
            "account_handle": profile["handle"],
            "status": "draft",
            "source": "auto_job",
            "schema_version": artefact["schema_version"],
            "artefact": artefact,
            "coverage": artefact["coverage"],
        },
        keys=("account_handle",),
    )
    store.update("creator_profiles", {"deep_status": "brief_draft"}, id=profile["id"])
    finish_run(run["id"], status="completed", counters=artefact["coverage"], store=store)
    return {"status": "completed", "artefact": artefact}


def run_caption_hook(text: str) -> dict[str, Any]:
    return {"caption_hook": caption_hook(text)}


def _past_deadline(deadline: str, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    hour, minute = (int(part) for part in deadline.split(":", 1))
    return now.hour * 60 + now.minute >= hour * 60 + minute


def run_drain(*, deadline: str = "02:45", now: datetime | None = None) -> dict[str, Any]:
    """L1/L2 drain. Never ingest, never promote, never activate_account."""
    assert_isolated_from_docmap()
    if _past_deadline(deadline, now=now):
        return {
            "status": "blocked",
            "reason": "deadline",
            "deadline": deadline,
            "stages": {},
        }
    stages: dict[str, Any] = {}
    stages["profile"] = run_profile()
    if _past_deadline(deadline, now=now):
        return {"status": "blocked", "reason": "deadline", "deadline": deadline, "stages": stages}
    stages["hydrate"] = run_hydrate()
    if _past_deadline(deadline, now=now):
        return {"status": "blocked", "reason": "deadline", "deadline": deadline, "stages": stages}
    stages["classify"] = run_classify()
    stages["score"] = run_score()
    stages["enqueue_deep"] = run_enqueue_deep()
    stages["link"] = {"skipped": True, "reason": "gtm_creators_link_not_wired"}
    failed = any((s.get("status") in {"blocked", "failed"} for s in stages.values() if isinstance(s, dict)))
    return {
        "status": "blocked" if failed else "completed",
        "deadline": deadline,
        "stages": stages,
    }


def run_sunday_refresh() -> dict[str, Any]:
    """Re-score, rebuild boards, enqueue newly good-fit. No ingest."""
    assert_isolated_from_docmap()
    return {
        "status": "completed",
        "score": run_score(),
        "enqueue_deep": run_enqueue_deep(),
    }


def dispatch(args: Any) -> dict[str, Any]:
    command = args.command
    if command == "status":
        return run_status()
    if command == "import-handles":
        return run_import_handles(Path(args.file))
    if command == "seed-import":
        return run_seed_import(Path(args.file))
    if command == "profile":
        html = Path(args.html) if getattr(args, "html", None) else None
        return run_profile(handle=getattr(args, "handle", None), html=html)
    if command == "hydrate":
        fixture = Path(args.fixture) if getattr(args, "fixture", None) else None
        return run_hydrate(
            handle=getattr(args, "handle", None),
            playlist_end=getattr(args, "playlist_end", 23),
            fixture=fixture,
        )
    if command == "classify":
        return run_classify(handle=getattr(args, "handle", None))
    if command == "score":
        return run_score()
    if command == "rebuild-specialty-stats":
        return run_rebuild_specialty_stats()
    if command == "enqueue-deep":
        return run_enqueue_deep()
    if command == "write-brief":
        sample = Path(args.sample) if getattr(args, "sample", None) else None
        return run_write_brief(args.handle, sample_path=sample)
    if command == "drain":
        return run_drain(deadline=getattr(args, "deadline", "02:45"))
    if command == "sunday-refresh":
        return run_sunday_refresh()
    raise SystemExit(f"Unknown creators command: {command}")
