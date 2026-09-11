"""Shared TikTok content_posts helpers for MCP tools."""

from __future__ import annotations

import statistics
from datetime import date, datetime, timezone
from typing import Any, Literal

from common.supabase_client import get_client

SortBy = Literal[
    "views",
    "likes",
    "engagement",
    "saves_per_1k",
    "comments_per_1k",
    "shares_per_1k",
    "posted_at",
]

WinnerBy = Literal["views", "saves_per_1k", "engagement"]

TIKTOK_POST_COLUMNS = (
    "id, platform_post_id, title, post_url, posted_at, hook, caption, transcript, "
    "metrics, metadata, topic, format, account_handle, owner_scope"
)


DEFAULT_ACCOUNT = "docmap"

# Set to False if the required account column is missing. Reads then fail closed
# rather than silently serving a mixed library.
_ACCOUNT_COLUMN_AVAILABLE = True


def account_scope_enforced() -> bool:
    return _ACCOUNT_COLUMN_AVAILABLE


def _missing_account_column(exc: Exception) -> bool:
    text = str(exc).lower()
    return "account_handle" in text and (
        "column" in text or "does not exist" in text or "schema" in text
    )


def _account_scope_error() -> RuntimeError:
    return RuntimeError(
        "content_posts.account_handle is unavailable; apply sql/013_peer_libraries.sql "
        "before reading TikTok libraries"
    )


def _validate_account_rows(rows: list[dict[str, Any]], account: str | None) -> None:
    if account is None:
        return
    mismatched = [
        str(row.get("platform_post_id"))
        for row in rows
        if row.get("account_handle") != account
    ]
    if mismatched:
        raise RuntimeError(
            f"Account-scoped TikTok read for '{account}' returned {len(mismatched)} "
            "row(s) from another or unlabelled account; refusing mixed output"
        )


def fetch_tiktok_posts(
    *, limit: int = 500, account: str | None = DEFAULT_ACCOUNT
) -> list[dict[str, Any]]:
    """Posts for one account, newest first.

    The account filter is applied in SQL, *before* the row limit. That ordering
    matters: a peer library of ~1,372 posts would otherwise fill the 500-row
    window and push DocMap's posts out of every read.

    Pass account=None only to deliberately read across libraries.
    """
    global _ACCOUNT_COLUMN_AVAILABLE

    def _query(with_account: bool, *, offset: int, page_size: int):
        q = (
            get_client()
            .table("content_posts")
            .select(TIKTOK_POST_COLUMNS)
            .eq("platform", "tiktok")
        )
        if with_account and account is not None:
            q = q.eq("account_handle", account)
        return (
            q.order("posted_at", desc=True)
            .range(offset, offset + page_size - 1)
            .execute()
            .data
            or []
        )

    if account is not None and not _ACCOUNT_COLUMN_AVAILABLE:
        raise _account_scope_error()

    rows: list[dict[str, Any]] = []
    while len(rows) < limit:
        page_size = min(1000, limit - len(rows))
        try:
            page = _query(account is not None, offset=len(rows), page_size=page_size)
        except Exception as exc:  # noqa: BLE001
            if account is not None and _missing_account_column(exc):
                _ACCOUNT_COLUMN_AVAILABLE = False
                raise _account_scope_error() from exc
            raise
        rows.extend(page)
        if len(page) < page_size:
            break
    _validate_account_rows(rows, account)
    return rows


def fetch_tiktok_post(
    video_id: str, *, account: str | None = DEFAULT_ACCOUNT
) -> dict[str, Any] | None:
    """One post, scoped to an account so a peer video cannot leak into a
    DocMap session by id alone."""
    global _ACCOUNT_COLUMN_AVAILABLE

    def _query(with_account: bool):
        q = (
            get_client()
            .table("content_posts")
            .select(TIKTOK_POST_COLUMNS)
            .eq("platform", "tiktok")
            .eq("platform_post_id", video_id)
        )
        if with_account and account is not None:
            q = q.eq("account_handle", account)
        return q.limit(1).execute().data or []

    if account is not None and not _ACCOUNT_COLUMN_AVAILABLE:
        raise _account_scope_error()
    if account is None:
        rows = _query(False)
    else:
        try:
            rows = _query(True)
        except Exception as exc:  # noqa: BLE001
            if _missing_account_column(exc):
                _ACCOUNT_COLUMN_AVAILABLE = False
                raise _account_scope_error() from exc
            else:
                raise
    _validate_account_rows(rows, account)
    return rows[0] if rows else None


def saves_per_1k(metrics: dict[str, Any]) -> float:
    if metrics.get("saves_per_1k_views") is not None:
        return float(metrics["saves_per_1k_views"])
    views = metrics.get("views")
    saves = metrics.get("saves")
    if views and saves:
        return round((saves / views) * 1000, 2)
    return 0.0


def comments_per_1k(metrics: dict[str, Any]) -> float:
    if metrics.get("comments_per_1k_views") is not None:
        return float(metrics["comments_per_1k_views"])
    views = metrics.get("views")
    comments = metrics.get("comments")
    if views and comments:
        return round((comments / views) * 1000, 2)
    return 0.0


def shares_per_1k(metrics: dict[str, Any]) -> float:
    if metrics.get("shares_per_1k_views") is not None:
        return float(metrics["shares_per_1k_views"])
    views = metrics.get("views")
    shares = metrics.get("shares")
    if views and shares:
        return round((shares / views) * 1000, 2)
    return 0.0


def engagement_total(metrics: dict[str, Any]) -> float:
    likes = int(metrics.get("likes") or 0)
    comments = int(metrics.get("comments") or 0)
    shares = int(metrics.get("shares") or 0)
    return float(likes + comments + shares)


def sort_score(row: dict[str, Any], sort_by: SortBy) -> float:
    metrics = row.get("metrics") or {}
    if sort_by == "views":
        return float(metrics.get("views") or 0)
    if sort_by == "likes":
        return float(metrics.get("likes") or 0)
    if sort_by == "engagement":
        return engagement_total(metrics)
    if sort_by == "saves_per_1k":
        return saves_per_1k(metrics)
    if sort_by == "comments_per_1k":
        return comments_per_1k(metrics)
    if sort_by == "shares_per_1k":
        return shares_per_1k(metrics)
    posted_at = row.get("posted_at")
    if not posted_at:
        return 0.0
    return float(str(posted_at).replace("Z", "+00:00")[:26].replace("T", "").replace(":", "").replace("-", "") or 0)


def rank_posts(rows: list[dict[str, Any]], sort_by: SortBy) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: sort_score(r, sort_by), reverse=True)


def cohort_medians(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {"views": 0.0, "saves_per_1k": 0.0, "engagement": 0.0}
    views = [float((r.get("metrics") or {}).get("views") or 0) for r in rows]
    saves = [saves_per_1k(r.get("metrics") or {}) for r in rows]
    eng = [engagement_total(r.get("metrics") or {}) for r in rows]
    return {
        "views": statistics.median(views),
        "saves_per_1k": statistics.median(saves),
        "engagement": statistics.median(eng),
    }


def performance_tier(
    row: dict[str, Any],
    medians: dict[str, float],
    *,
    sort_by: SortBy = "views",
) -> str:
    """Return outperform | typical | underperform vs cohort median on sort_by metric."""
    score = sort_score(row, sort_by)
    median = medians.get(sort_by if sort_by in medians else "views", 0.0)
    if median <= 0:
        return "typical"
    ratio = score / median
    if ratio >= 1.25:
        return "outperform"
    if ratio <= 0.75:
        return "underperform"
    return "typical"


def filter_by_date(
    rows: list[dict[str, Any]],
    *,
    since: str | None = None,
    until: str | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        posted = str(row.get("posted_at") or "")[:10]
        if since and posted < since[:10]:
            continue
        if until and posted > until[:10]:
            continue
        out.append(row)
    return out


def post_summary(row: dict[str, Any], *, medians: dict[str, float] | None = None) -> dict[str, Any]:
    metrics = row.get("metrics") or {}
    meta = row.get("metadata") or {}
    hook_detail = meta.get("hook_detail") or {}
    summary: dict[str, Any] = {
        "video_id": row.get("platform_post_id"),
        "account_handle": row.get("account_handle"),
        "title": row.get("title"),
        "hook": row.get("hook"),
        "hook_source": hook_detail.get("hook_source"),
        "spoken_hook": hook_detail.get("spoken_hook"),
        "caption_hook": hook_detail.get("caption_hook"),
        "onscreen_hook": hook_detail.get("onscreen_hook"),
        "topic": row.get("topic"),
        "format": row.get("format"),
        "post_url": row.get("post_url"),
        "posted_at": row.get("posted_at"),
        "metrics": metrics,
        "views": metrics.get("views"),
        "engagement": int(engagement_total(metrics)),
        "saves_per_1k_views": saves_per_1k(metrics),
    }
    if medians is not None:
        summary["tier_vs_cohort_views"] = performance_tier(row, medians, sort_by="views")
        summary["tier_vs_cohort_saves_per_1k"] = performance_tier(
            row, medians, sort_by="saves_per_1k"
        )
    stored_tier = meta.get("performance_tier")
    if stored_tier:
        summary["performance_tier"] = stored_tier
    if meta.get("is_catalog_stub"):
        summary["is_catalog_stub"] = True
        summary["transcript_status"] = meta.get("transcript_status") or "pending"
    return summary


def library_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dates = [str(r.get("posted_at") or "")[:10] for r in rows if r.get("posted_at")]
    newest = max(dates) if dates else None
    stubs = sum(1 for r in rows if (r.get("metadata") or {}).get("is_catalog_stub"))
    today = datetime.now(timezone.utc).date()
    staleness_warning = None
    pending_transcript = stubs
    if newest:
        days_old = (today - date.fromisoformat(newest)).days
        if days_old > 7:
            staleness_warning = (
                f"Synced library newest post is {newest} ({days_old} days behind UTC today). "
                "An empty date filter may mean stale sync — not that publishing stopped. "
                "Run tiktok refresh && sync-supabase."
            )
    return {
        "library_video_count": len(rows),
        "library_newest_posted_at": newest,
        "catalog_stub_count": stubs,
        "pending_transcript_count": pending_transcript,
        "staleness_warning": staleness_warning,
    }


def winner_video_id(
    video_id: str,
    partner_id: str,
    video_metrics: dict[str, Any],
    partner_metrics: dict[str, Any],
    *,
    winner_by: WinnerBy,
) -> str:
    if winner_by == "views":
        a = int(video_metrics.get("views") or 0)
        b = int(partner_metrics.get("views") or 0)
    elif winner_by == "engagement":
        a = int(engagement_total(video_metrics))
        b = int(engagement_total(partner_metrics))
    else:
        a = saves_per_1k(video_metrics)
        b = saves_per_1k(partner_metrics)
    if a > b:
        return video_id
    if b > a:
        return partner_id
    return video_id


def aggregate_ab_tests(
    rows: list[dict[str, Any]],
    *,
    winner_by: WinnerBy = "views",
    dedupe_by_pair_id: bool = False,
) -> list[dict[str, Any]]:
    """Return A/B pair edges. Default: all unique video↔partner edges (not collapsed by pair_id)."""
    posts_by_video: dict[str, dict[str, Any]] = {}
    for row in rows:
        vid = row.get("platform_post_id")
        if vid:
            posts_by_video[str(vid)] = row

    tests: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str]] = set()
    seen_pair_ids: set[str] = set()

    for row in rows:
        video_id = str(row.get("platform_post_id") or "")
        meta = row.get("metadata") or {}
        hook_detail = meta.get("hook_detail") or {}
        ab_learning = meta.get("ab_learning") or {}

        for ref in meta.get("ab_pairs") or []:
            pair_id = ref.get("pair_id")
            partner_id = str(ref.get("partner_video_id") or "")
            if not pair_id or not partner_id:
                continue

            edge = tuple(sorted([video_id, partner_id]))
            if edge in seen_edges:
                continue
            if dedupe_by_pair_id and pair_id in seen_pair_ids:
                continue
            seen_edges.add(edge)
            if dedupe_by_pair_id:
                seen_pair_ids.add(pair_id)

            partner = posts_by_video.get(partner_id, {})
            partner_meta = partner.get("metadata") or {}
            partner_hook_detail = partner_meta.get("hook_detail") or {}
            video_metrics = row.get("metrics") or {}
            partner_metrics = partner.get("metrics") or {}

            learning = ref.get("learning")
            if ab_learning.get("pair_id") == pair_id and ab_learning.get("learning"):
                learning = ab_learning["learning"]

            winner = winner_video_id(
                video_id, partner_id, video_metrics, partner_metrics, winner_by=winner_by
            )
            loser = partner_id if winner == video_id else video_id

            tests.append(
                {
                    "pair_id": pair_id,
                    "video_id": video_id,
                    "partner_video_id": partner_id,
                    "learning": learning,
                    "ab_learning": ab_learning if ab_learning.get("pair_id") == pair_id else None,
                    "performance_difference": ref.get("performance_difference"),
                    "video_metrics": video_metrics,
                    "partner_metrics": partner_metrics,
                    "video_hook": row.get("hook"),
                    "partner_hook": partner.get("hook"),
                    "video_hook_detail": hook_detail,
                    "partner_hook_detail": partner_hook_detail,
                    "video_hook_source": hook_detail.get("hook_source"),
                    "partner_hook_source": partner_hook_detail.get("hook_source"),
                    "video_views": video_metrics.get("views"),
                    "partner_views": partner_metrics.get("views"),
                    "video_saves_per_1k": saves_per_1k(video_metrics),
                    "partner_saves_per_1k": saves_per_1k(partner_metrics),
                    "video_engagement": int(engagement_total(video_metrics)),
                    "partner_engagement": int(engagement_total(partner_metrics)),
                    "winner_by": winner_by,
                    "winner_video_id": winner,
                    "loser_video_id": loser,
                }
            )

    return tests


# ---------------------------------------------------------------------------
# Rolling-local comparison (large, multi-year libraries)
# ---------------------------------------------------------------------------
# A global median across a three-year catalog mostly ranks posts by how long
# they have been live. These helpers compare each post against its neighbours
# in publish time instead.

ROLLING_WINDOW = 40
MIN_ROLLING_WINDOW = 12
INSUFFICIENT_WINDOW = "insufficient_window"


def _metric_or_none(row: dict[str, Any], key: str) -> float | None:
    """Absent metrics stay None. A zero would be counted as a measurement."""
    value = (row.get("metrics") or {}).get(key)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _window_bounds(index: int, total: int, window: int) -> tuple[int, int]:
    """Centred window that slides inward at the edges rather than shrinking."""
    if total <= window:
        return 0, total
    half = window // 2
    start = max(0, index - half)
    end = start + window
    if end > total:
        end, start = total, total - window
    return start, end


def rolling_local_stats(
    rows: list[dict[str, Any]],
    *,
    window: int = ROLLING_WINDOW,
    min_window: int = MIN_ROLLING_WINDOW,
) -> dict[str, dict[str, Any]]:
    """Per-video ratio against the local median, keyed by platform_post_id.

    Computed over every row supplied, never a filtered subset, so a date filter
    cannot move a post's tier.
    """
    ordered = sorted(
        rows,
        key=lambda r: (str(r.get("posted_at") or ""), str(r.get("platform_post_id"))),
    )
    total = len(ordered)
    views = [_metric_or_none(r, "views") for r in ordered]
    out: dict[str, dict[str, Any]] = {}

    for i, row in enumerate(ordered):
        start, end = _window_bounds(i, total, min(window + 1, total))
        present = [v for j, v in enumerate(views[start:end], start=start) if j != i and v is not None]
        vid = str(row.get("platform_post_id"))
        score = views[i]

        if len(present) < min_window:
            out[vid] = {
                "views_ratio": None,
                "tier": INSUFFICIENT_WINDOW,
                "local_median_views": None,
                "window_n": len(present),
                "window_from": str(ordered[start].get("posted_at") or "")[:10] or None,
                "window_to": str(ordered[end - 1].get("posted_at") or "")[:10] or None,
            }
            continue

        median = statistics.median(present)
        ratio = round(score / median, 3) if score is not None and median else None
        if score is None:
            tier = "unknown"
        elif ratio is None:
            tier = "typical"
        elif ratio >= 1.25:
            tier = "outperform"
        elif ratio <= 0.75:
            tier = "underperform"
        else:
            tier = "typical"

        out[vid] = {
            "views_ratio": ratio,
            "tier": tier,
            "local_median_views": round(median, 1),
            "window_n": len(present),
            "window_from": str(ordered[start].get("posted_at") or "")[:10] or None,
            "window_to": str(ordered[end - 1].get("posted_at") or "")[:10] or None,
        }
    return out


def cadence_fields(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Deterministic publishing-rhythm facts per post.

    Measurements only: gap since the previous post and how many posts share the
    same ISO week. What the rhythm *means* is Claude's to judge.
    """
    ordered = sorted(
        rows,
        key=lambda r: (str(r.get("posted_at") or ""), str(r.get("platform_post_id"))),
    )
    week_counts: dict[str, int] = {}
    for row in ordered:
        posted = str(row.get("posted_at") or "")[:10]
        if not posted:
            continue
        try:
            iso = date.fromisoformat(posted).isocalendar()
        except ValueError:
            continue
        key = f"{iso[0]}-W{iso[1]:02d}"
        week_counts[key] = week_counts.get(key, 0) + 1

    out: dict[str, dict[str, Any]] = {}
    prev: date | None = None
    for row in ordered:
        vid = str(row.get("platform_post_id"))
        posted = str(row.get("posted_at") or "")[:10]
        try:
            current = date.fromisoformat(posted) if posted else None
        except ValueError:
            current = None
        gap = (current - prev).days if current and prev else None
        week_key = None
        if current:
            iso = current.isocalendar()
            week_key = f"{iso[0]}-W{iso[1]:02d}"
        out[vid] = {
            "days_since_previous_post": gap,
            "iso_week": week_key,
            "posts_in_same_week": week_counts.get(week_key) if week_key else None,
        }
        if current:
            prev = current
    return out
