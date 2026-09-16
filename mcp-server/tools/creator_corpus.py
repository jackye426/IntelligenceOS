"""L1/L2 doctor-creator corpus tools. Paginated boards, never transcript dumps."""

from __future__ import annotations

import copy
import json
from typing import Any

from common.audit import log_tool_call
from tools.corpus_store import LEAN_FIELDS, get_corpus, lean_row

DEFAULT_PAGE = 50
HARD_CAP = 100
COMPARE_CAP = 8
PLAYBOOK_SECTIONS = ("0", "1", "2", "5", "9", "11")
FORBIDDEN_PAYLOAD_KEYS = {
    "transcript",
    "transcripts",
    "transcript_segments",
    "caption",
    "captions",
    "packets",
    "posts",
}

ORDER_MAP = {
    "customer_score": "customer_score",
    "research_score": "research_score",
    "saves": "median_saves_per_1k",
    "followers": "follower_count",
    "posts_30d": "posts_30d",
}

NOT_MEASURABLE = {
    "follower_history": (
        "Not available until two profile snapshots exist. Last-23/50 videos are "
        "current packaging, not growth."
    ),
    "bookings": "Not available unless an appointment-availability pointer exists.",
    "spoken_first_15s": (
        "Spoken first-15s rules need timestamped L3 transcripts. Do not infer them "
        "from L2 caption_hooks."
    ),
    "retention": "Average watch time and finish rate are owner-only Studio metrics.",
    "traffic_sources": "No paid/organic or For You vs follow split on public data.",
}


class CorpusError(ValueError):
    """Raised for bad corpus tool arguments."""


def _page_limit(limit: int | None) -> int:
    value = DEFAULT_PAGE if limit is None else int(limit)
    if value < 1:
        raise CorpusError("limit must be >= 1")
    return min(value, HARD_CAP)


def _strip_forbidden(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: _strip_forbidden(value)
            for key, value in payload.items()
            if key not in FORBIDDEN_PAYLOAD_KEYS
        }
    if isinstance(payload, list):
        return [_strip_forbidden(item) for item in payload]
    return payload


def _guidelines_excerpt(artefact: dict[str, Any] | None) -> dict[str, Any] | None:
    if not artefact:
        return None
    sections = artefact.get("sections") or {}
    excerpt = {}
    for key in PLAYBOOK_SECTIONS:
        excerpt[key] = _strip_forbidden(copy.deepcopy(sections.get(key)))
    return {
        "schema_version": artefact.get("schema_version"),
        "sections": excerpt,
    }


def _paginate(rows: list[dict[str, Any]], cursor: int, limit: int) -> dict[str, Any]:
    total = len(rows)
    page = rows[cursor : cursor + limit]
    next_cursor = cursor + len(page) if cursor + len(page) < total else None
    return {
        "total_rows": total,
        "returned_rows": len(page),
        "next_cursor": next_cursor,
        "rows": page,
    }


def get_creator_corpus_summary() -> dict[str, Any]:
    corpus = get_corpus()
    profiles = corpus.list("creator_profiles")
    summary = f"profiles={len(profiles)}"
    try:

        def _counts(field: str) -> dict[str, int]:
            out: dict[str, int] = {}
            for row in profiles:
                key = str(row.get(field) or "unknown")
                out[key] = out.get(key, 0) + 1
            return out

        queued = corpus.count("creator_deep_job_items", eq={"status": "queued"})
        running = corpus.count("creator_deep_job_items", eq={"status": "running"})
        runs = corpus.list("creator_crawl_runs", order="started_at", desc=True, limit=10)
        seeds = corpus.list("creator_seeds", order="doctor_yield", desc=True, limit=20)
        result = {
            "profiles": len(profiles),
            "by_stage": _counts("stage"),
            "by_lane": _counts("lane"),
            "by_geo": _counts("geo_country"),
            "by_specialty": _counts("specialty_key"),
            "by_review": _counts("review_status"),
            "by_good_fit": _counts("good_fit"),
            "by_deep_status": _counts("deep_status"),
            "queue_depth": {"queued": queued, "running": running},
            "last_runs": [
                {
                    "command": r.get("command"),
                    "status": r.get("status"),
                    "counters": r.get("counters"),
                    "started_at": r.get("started_at"),
                }
                for r in runs
            ],
            "seed_yields": [
                {
                    "value": s.get("value"),
                    "slice": s.get("slice"),
                    "doctor_yield": s.get("doctor_yield"),
                    "customer_yield": s.get("customer_yield"),
                    "unique_new_authors": s.get("unique_new_authors"),
                }
                for s in seeds
            ],
        }
        log_tool_call(
            tool_name="get_creator_corpus_summary",
            request_summary=summary,
            success=True,
            entity_type="creator_corpus",
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_creator_corpus_summary",
            request_summary=summary,
            success=False,
            entity_type="creator_corpus",
            error=str(exc),
        )
        raise


def get_specialty_board(specialty_key: str) -> dict[str, Any]:
    key = (specialty_key or "").strip().lower()
    if not key:
        raise CorpusError("specialty_key is required")
    corpus = get_corpus()
    row = corpus.get("creator_specialty_stats", specialty_key=key)
    if not row:
        return {"specialty_key": key, "found": False}
    exemplars = row.get("exemplar_handles") or {}
    return {
        "found": True,
        "specialty_key": key,
        "n_doctors": row.get("n_doctors"),
        "n_uk_private": row.get("n_uk_private"),
        "n_deep_libraries": row.get("n_deep_libraries"),
        "median_followers": row.get("median_followers"),
        "median_posts_30d": row.get("median_posts_30d"),
        "median_saves_per_1k": row.get("median_saves_per_1k"),
        "median_shares_per_1k": row.get("median_shares_per_1k"),
        "format_histogram": row.get("format_histogram"),
        "cta_histogram": row.get("cta_histogram"),
        "hook_job_histogram": row.get("hook_job_histogram"),
        "exemplar_handles": exemplars,
        "note": "Exemplars are handles only. Load cards with get_creator_profile / compare_creators.",
    }


def list_creators(
    *,
    lane: str | None = None,
    geo: str | None = None,
    specialty_key: str | None = None,
    min_score: float | None = None,
    min_followers: int | None = None,
    max_followers: int | None = None,
    review_status: str | None = None,
    deep_status: str | None = None,
    good_fit: bool | None = None,
    order: str = "research_score",
    cursor: int = 0,
    limit: int = DEFAULT_PAGE,
) -> dict[str, Any]:
    page_size = _page_limit(limit)
    order_col = ORDER_MAP.get(order)
    if not order_col:
        raise CorpusError(f"order must be one of {sorted(ORDER_MAP)}")
    corpus = get_corpus()
    rows = corpus.list("creator_corpus_current", order=order_col, desc=True)
    filtered: list[dict[str, Any]] = []
    score_field = "customer_score" if order_col == "customer_score" else "research_score"
    for row in rows:
        if lane and row.get("lane") != lane:
            continue
        if geo and str(row.get("geo_country") or "").upper() != geo.upper():
            continue
        if specialty_key and row.get("specialty_key") != specialty_key:
            continue
        if review_status and row.get("review_status") != review_status:
            continue
        if deep_status and row.get("deep_status") != deep_status:
            continue
        if good_fit is not None and bool(row.get("good_fit")) != bool(good_fit):
            continue
        followers = row.get("follower_count")
        if min_followers is not None and (followers is None or followers < min_followers):
            continue
        if max_followers is not None and (followers is None or followers > max_followers):
            continue
        score = row.get(score_field)
        if min_score is not None and (score is None or float(score) < float(min_score)):
            continue
        lean = {key: row.get(key) for key in LEAN_FIELDS}
        filtered.append(lean)
    page = _paginate(filtered, int(cursor or 0), page_size)
    dumped = json.dumps(page)
    if "transcript" in dumped or '"caption"' in dumped:
        raise CorpusError("list_creators refused a payload that included captions or transcripts")
    return page


def get_creator_profile(handle: str) -> dict[str, Any]:
    handle = (handle or "").strip().lstrip("@").lower()
    if not handle:
        raise CorpusError("handle is required")
    corpus = get_corpus()
    profile = corpus.get("creator_profiles", handle=handle)
    if not profile:
        return {"found": False, "handle": handle}
    card = corpus.get("creator_insight_cards", creator_profile_id=profile["id"])
    videos = corpus.list(
        "creator_videos",
        eq={"creator_profile_id": profile["id"]},
        order="posted_at",
        desc=True,
        limit=8,
    )
    snapshots = corpus.list(
        "creator_profile_snapshots",
        eq={"creator_profile_id": profile["id"]},
        order="captured_at",
        desc=True,
        limit=12,
    )
    links = corpus.list("creator_links", eq={"creator_profile_id": profile["id"]})
    job = corpus.get("creator_deep_job_items", item_key=profile["id"], kind="deep_ingest")
    brief = corpus.get("creator_peer_briefs", account_handle=handle)
    card_out = None
    if card:
        card_out = _strip_forbidden(copy.deepcopy(card))
        card_out.pop("output", None)
    return {
        "found": True,
        "handle": handle,
        "profile": lean_row(profile),
        "score_breakdown": profile.get("score_breakdown"),
        "lane_reasons": profile.get("lane_reasons"),
        "insight_card": card_out,
        "caption_hooks": [v.get("caption_hook") for v in videos if v.get("caption_hook")][:8],
        "snapshots": [
            {
                "captured_at": s.get("captured_at"),
                "follower_count": s.get("follower_count"),
                "heart_count": s.get("heart_count"),
                "video_count": s.get("video_count"),
            }
            for s in snapshots
        ],
        "links": links,
        "deep_status": profile.get("deep_status"),
        "ingest_status": (job or {}).get("status"),
        "brief_status": (brief or {}).get("status"),
        "review_status": profile.get("review_status"),
    }


def compare_creators(handles: list[str]) -> dict[str, Any]:
    cleaned = [(h or "").strip().lstrip("@").lower() for h in handles or []]
    cleaned = [h for h in cleaned if h]
    if not cleaned:
        raise CorpusError("handles are required")
    if len(cleaned) > COMPARE_CAP:
        raise CorpusError(f"compare_creators accepts at most {COMPARE_CAP} handles")
    corpus = get_corpus()
    rows = []
    for handle in cleaned:
        profile = corpus.get("creator_profiles", handle=handle)
        if not profile:
            rows.append({"handle": handle, "found": False})
            continue
        card = corpus.get("creator_insight_cards", creator_profile_id=profile["id"]) or {}
        rows.append(
            {
                "handle": handle,
                "found": True,
                "follower_count": profile.get("follower_count"),
                "posts_30d": profile.get("posts_30d"),
                "median_saves_per_1k": profile.get("median_saves_per_1k"),
                "median_shares_per_1k": profile.get("median_shares_per_1k"),
                "median_views": profile.get("median_views"),
                "growth_intent_level": profile.get("growth_intent_level"),
                "positioning_line": profile.get("positioning_line") or card.get("positioning_line"),
                "hook_jobs": profile.get("hook_jobs") or card.get("hook_jobs"),
                "format_mix": profile.get("format_mix") or card.get("format_mix"),
                "cta_mix": profile.get("cta_mix") or card.get("cta_types"),
                "lane": profile.get("lane"),
                "customer_score": profile.get("customer_score"),
                "research_score": profile.get("research_score"),
                "deep_status": profile.get("deep_status"),
            }
        )
    dumped = json.dumps(rows)
    if "transcript" in dumped:
        raise CorpusError("compare_creators refused transcripts")
    return {"creators": rows, "returned_rows": len(rows)}


def get_specialty_playbook(specialty_key: str) -> dict[str, Any]:
    board = get_specialty_board(specialty_key)
    if not board.get("found"):
        return {**board, "guidelines": [], "not_measurable": NOT_MEASURABLE}
    corpus = get_corpus()
    exemplars = board.get("exemplar_handles") or {}
    handles: list[str] = []
    for bucket in ("high_saves", "high_efficiency", "mid_size", "uk_private", "contrast_vanity"):
        for handle in exemplars.get(bucket) or []:
            if handle not in handles:
                handles.append(handle)
    cited = []
    for handle in handles[:8]:
        brief = corpus.get("creator_peer_briefs", account_handle=handle)
        if not brief or brief.get("status") not in {"confirmed", "draft"}:
            continue
        cited.append(
            {
                "handle": handle,
                "status": brief.get("status"),
                "unreviewed": brief.get("status") == "draft",
                "guidelines": _guidelines_excerpt(brief.get("artefact") or {}),
            }
        )
    histograms = {
        "hook_jobs": board.get("hook_job_histogram"),
        "formats": board.get("format_histogram"),
        "ctas": board.get("cta_histogram"),
    }
    result = {
        "specialty_key": board["specialty_key"],
        "stats": {
            "n_doctors": board.get("n_doctors"),
            "median_saves_per_1k": board.get("median_saves_per_1k"),
            "median_followers": board.get("median_followers"),
        },
        "histograms": histograms,
        "exemplar_handles": exemplars,
        "cited_guidelines": cited,
        "not_measurable": NOT_MEASURABLE,
        "note": (
            "Cited L3 sections are thesis / first-15s / beats / caption spec / "
            "anti-patterns / checklist. Spoken packets stay in get_peer_content_batch "
            "for one account."
        ),
    }
    return result


def list_creator_seeds(*, order: str = "doctor_yield", cursor: int = 0, limit: int = DEFAULT_PAGE) -> dict[str, Any]:
    if order != "doctor_yield":
        raise CorpusError("order must be doctor_yield")
    page_size = _page_limit(limit)
    rows = get_corpus().list("creator_seeds", order="doctor_yield", desc=True)
    page = _paginate(rows, int(cursor or 0), page_size)
    page["seeds"] = [
        {
            "value": s.get("value"),
            "slice": s.get("slice"),
            "source_type": s.get("source_type"),
            "priority": s.get("priority"),
            "status": s.get("status"),
            "doctor_yield": s.get("doctor_yield"),
            "customer_yield": s.get("customer_yield"),
            "unique_new_authors": s.get("unique_new_authors"),
            "hits_total": s.get("hits_total"),
        }
        for s in page.pop("rows")
    ]
    return page


def review_creator(
    handle: str,
    *,
    review_status: str | None = None,
    review_lane_override: str | None = None,
    review_note: str | None = None,
    do_not_contact: bool | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    handle = (handle or "").strip().lstrip("@").lower()
    if not handle:
        raise CorpusError("handle is required")
    corpus = get_corpus()
    profile = corpus.get("creator_profiles", handle=handle)
    if not profile:
        raise CorpusError(f"unknown handle {handle}")
    patch = {
        "review_status": review_status or profile.get("review_status"),
        "review_lane_override": review_lane_override
        if review_lane_override is not None
        else profile.get("review_lane_override"),
        "review_note": review_note if review_note is not None else profile.get("review_note"),
        "do_not_contact": profile.get("do_not_contact") if do_not_contact is None else do_not_contact,
    }
    preview = {"handle": handle, "preview": not confirmed, "would_write": patch}
    if not confirmed:
        return preview
    corpus.update("creator_profiles", patch, id=profile["id"])
    return {"handle": handle, "written": True, "review": patch}
