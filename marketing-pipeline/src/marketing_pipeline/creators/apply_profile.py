"""Write fetched profile facts. Failures must not overwrite good facts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from marketing_pipeline.creators.bio_parse import parse_bio
from marketing_pipeline.creators.paths import normalise_handle
from marketing_pipeline.creators.profile import ProfileFetchError
from marketing_pipeline.creators.screen import has_medical_signal, screen_profile
from marketing_pipeline.creators.store import get_store


def apply_profile_success(existing: dict[str, Any], fields: dict[str, Any], *, store=None) -> dict[str, Any]:
    store = store or get_store()
    handle = normalise_handle(fields.get("handle") or existing["handle"])
    parsed = parse_bio(fields.get("nickname"), fields.get("bio"), fields.get("bio_link"))
    if fields.get("private_account"):
        patch = {
            "stage": "unavailable",
            "excluded_reason": "private",
            "work_status": "blocked",
            "handle": handle,
            "profile_fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        store.update("creator_profiles", patch, id=existing["id"])
        return {**existing, **patch}

    screened = screen_profile(
        nickname=fields.get("nickname"),
        bio=fields.get("bio"),
        video_count=fields.get("video_count"),
        is_organization=fields.get("is_organization"),
    )
    if screened["screen_result"] == "exclude":
        stage = "excluded"
        work = "blocked"
        excluded = ",".join(screened["screen_reasons"])
    else:
        stage = "screened"
        work = "ready"
        excluded = None

    real_id = fields.get("tiktok_user_id") or existing.get("tiktok_user_id")
    patch = {
        **{k: v for k, v in fields.items() if v is not None},
        "tiktok_user_id": real_id,
        "handle": handle,
        **parsed,
        "screen_result": screened["screen_result"],
        "screen_reasons": screened["screen_reasons"],
        "stage": stage,
        "work_status": work,
        "excluded_reason": excluded,
        "profile_fetched_at": datetime.now(timezone.utc).isoformat(),
        "geo_country": parsed.get("geo_country") or existing.get("geo_country"),
        "geo_confidence": parsed.get("geo_confidence") or existing.get("geo_confidence"),
    }
    history = list(existing.get("handle_history") or [])
    if existing.get("handle") and existing["handle"] != handle and existing["handle"] not in history:
        history.append(existing["handle"])
    patch["handle_history"] = history
    store.update("creator_profiles", patch, id=existing["id"])
    store.insert(
        "creator_profile_snapshots",
        {
            "creator_profile_id": existing["id"],
            "follower_count": fields.get("follower_count"),
            "following_count": fields.get("following_count"),
            "heart_count": fields.get("heart_count"),
            "video_count": fields.get("video_count"),
            "source": "profile_html",
        },
    )
    return store.get("creator_profiles", id=existing["id"]) or {**existing, **patch}


def apply_profile_failure(existing: dict[str, Any], exc: ProfileFetchError, *, store=None) -> dict[str, Any]:
    """Record the error without touching profile facts (postmortem #1)."""
    store = store or get_store()
    if exc.kind == "unavailable":
        stage = "unavailable"
        work = "blocked"
    else:
        stage = existing.get("stage") or "discovered"
        work = "retry"
    store.update(
        "creator_profiles",
        {
            "last_error": str(exc),
            "work_status": work,
            "stage": stage if exc.kind == "unavailable" else existing.get("stage"),
            "excluded_reason": "unavailable" if exc.kind == "unavailable" else existing.get("excluded_reason"),
        },
        id=existing["id"],
    )
    return existing


def prescreen_or_exclude(profile: dict[str, Any], *, generic_seed: bool, store=None) -> dict[str, Any]:
    if not generic_seed:
        return profile
    if has_medical_signal(profile.get("nickname"), profile.get("bio") or profile.get("author_signature")):
        return profile
    store = store or get_store()
    store.update(
        "creator_profiles",
        {
            "stage": "excluded",
            "excluded_reason": "no_medical_signal_prescreen",
            "work_status": "blocked",
        },
        id=profile["id"],
    )
    return {**profile, "stage": "excluded"}
