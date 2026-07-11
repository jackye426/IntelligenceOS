"""Instagram pipeline orchestration."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from marketing_pipeline import config
from marketing_pipeline.instagram.models import (
    InstagramMarketingDataset,
    InstagramMetrics,
    InstagramPost,
)
from marketing_pipeline.instagram.stages.extract_components import (
    build_components,
    first_text_line,
    infer_format,
)
from marketing_pipeline.instagram.stages.fetch_posts import fetch_posts, load_raw_posts
from marketing_pipeline.instagram.stages.import_content_tracker import (
    load_tracker_rows,
    shortcode_from_url,
)
from marketing_pipeline.instagram.sync.supabase import run_sync


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_denominator(metrics: dict[str, Any]) -> int | None:
    return _int(metrics.get("reach")) or _int(metrics.get("views")) or _int(metrics.get("plays"))


def _build_metrics(raw: dict[str, Any], tracker: dict[str, Any] | None) -> InstagramMetrics:
    tracker_metrics = dict((tracker or {}).get("metrics") or {})
    metrics: dict[str, Any] = {
        "likes": tracker_metrics.get("likes", raw.get("likes")),
        "comments": tracker_metrics.get("comments", raw.get("comments")),
        "views": tracker_metrics.get("views", raw.get("video_view_count")),
        "plays": tracker_metrics.get("plays"),
        "reach": tracker_metrics.get("reach"),
        "saves": tracker_metrics.get("saves"),
        "shares": tracker_metrics.get("shares"),
        "profile_visits": tracker_metrics.get("profile_visits"),
        "follows": tracker_metrics.get("follows_attributed", tracker_metrics.get("follows")),
        "external_link_taps": tracker_metrics.get("external_link_taps"),
        "avg_watch_time_sec": tracker_metrics.get("avg_watch_time_sec"),
        "skip_rate": tracker_metrics.get("skip_rate"),
    }
    likes = _int(metrics.get("likes")) or 0
    comments = _int(metrics.get("comments")) or 0
    saves = _int(metrics.get("saves")) or 0
    shares = _int(metrics.get("shares")) or 0
    engagement = likes + comments + saves + shares
    denom = _metric_denominator(metrics)
    metrics["engagement"] = engagement
    if denom:
        metrics["engagement_per_1k"] = round((engagement / denom) * 1000, 2)
        metrics["saves_per_1k"] = round((saves / denom) * 1000, 2)
        metrics["shares_per_1k"] = round((shares / denom) * 1000, 2)
        metrics["comments_per_1k"] = round((comments / denom) * 1000, 2)
    return InstagramMetrics(**{k: v for k, v in metrics.items() if v is not None})


def _match_tracker(raw: dict[str, Any], tracker_rows: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    keys = [
        raw.get("shortcode"),
        raw.get("mediaid"),
        raw.get("url"),
        shortcode_from_url(raw.get("url")),
    ]
    for key in keys:
        if key and str(key) in tracker_rows:
            return tracker_rows[str(key)]
    return None


def _post_id(raw: dict[str, Any], tracker: dict[str, Any] | None) -> str:
    return (
        str(raw.get("mediaid") or "")
        or str((tracker or {}).get("post_id") or "")
        or str(raw.get("shortcode") or "")
    )


def build_dataset(
    *,
    account: str = config.INSTAGRAM_ACCOUNT,
    raw_path: Path | None = None,
    tracker_csv: Path | None = None,
) -> InstagramMarketingDataset:
    raw_posts = load_raw_posts(raw_path)
    tracker_rows = load_tracker_rows(tracker_csv)

    dataset = InstagramMarketingDataset(
        account=account,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    for raw in raw_posts:
        tracker = _match_tracker(raw, tracker_rows)
        post_id = _post_id(raw, tracker)
        if not post_id:
            continue
        source_layers = ["instaloader"]
        if tracker:
            source_layers.append("content_tracker_csv")

        fmt = infer_format(raw, tracker)
        caption = raw.get("caption") or (tracker or {}).get("caption")
        child_media = list(raw.get("child_media") or [])
        components = build_components(
            fmt=fmt,
            caption=caption,
            tracker=tracker,
            child_media=child_media,
            source_layers=source_layers,
        )
        metrics = _build_metrics(raw, tracker)
        title = (tracker or {}).get("topic") or first_text_line(caption)
        shortcode = raw.get("shortcode") or (tracker or {}).get("shortcode")
        url = raw.get("url") or (tracker or {}).get("permalink") or (
            f"https://www.instagram.com/p/{shortcode}/" if shortcode else ""
        )
        dataset.posts[post_id] = InstagramPost(
            post_id=post_id,
            shortcode=shortcode,
            url=url,
            posted_at=raw.get("date_utc") or (tracker or {}).get("publish_date"),
            caption=caption,
            title=title,
            topic=(tracker or {}).get("topic"),
            format=fmt,
            media_type=raw.get("typename"),
            media_url=raw.get("video_url") or raw.get("display_url"),
            thumbnail_url=raw.get("display_url"),
            child_media=child_media,
            metrics=metrics,
            components=components,
            raw_metadata={
                "source_layers": source_layers,
                "instaloader": raw,
                "content_tracker": tracker,
            },
        )

    return dataset


def write_dataset(dataset: InstagramMarketingDataset, path: Path | None = None) -> Path:
    target = path or config.INSTAGRAM_DATASET_JSON
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dataset.model_dump_json(indent=2), encoding="utf-8")
    return target


def build_strategy_brief(dataset: InstagramMarketingDataset) -> dict[str, Any]:
    posts = list(dataset.posts.values())
    by_format: dict[str, int] = {}
    newest = None
    for post in posts:
        by_format[post.format] = by_format.get(post.format, 0) + 1
        if post.posted_at:
            newest = max(newest or post.posted_at, post.posted_at)
    ranked = sorted(
        posts,
        key=lambda p: (
            p.metrics.follows
            or p.metrics.profile_visits
            or p.metrics.saves_per_1k
            or p.metrics.engagement_per_1k
            or p.metrics.engagement
            or 0
        ),
        reverse=True,
    )
    return {
        "0_meta": {
            "platform": "instagram",
            "account": dataset.account,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "metrics_as_of": dataset.generated_at,
            "post_count": len(posts),
            "newest_posted_at": newest,
            "format_counts": by_format,
        },
        "1_constitution": (
            "Instagram analysis is format-first: compare Reels, carousels, and static posts separately. "
            "Prefer owned conversion metrics when present; otherwise rank by engagement quality."
        ),
        "2_format_rules": {
            "reel": "Judge Reels by opening hook, watch metrics when available, comments, and intent actions.",
            "carousel": "Judge carousels by cover claim, slide structure, saves, shares, and comments.",
            "static": "Judge static posts by clarity of message, caption opening, CTA, and engagement quality.",
        },
        "3_approved_insights": [],
        "4_open_drafts": [],
        "5_anti_patterns": [],
        "6_reference_set": [
            {
                "post_id": post.post_id,
                "format": post.format,
                "title": post.title,
                "post_url": post.url,
                "posted_at": post.posted_at,
                "metrics": post.metrics.model_dump(exclude_none=True),
                "components": post.components.model_dump(exclude_none=True),
            }
            for post in ranked[:12]
        ],
        "7_decisions": {"open": [], "recent_closed": []},
        "8_changelog": [],
    }


def write_strategy_brief(dataset: InstagramMarketingDataset) -> Path:
    target = config.INSTAGRAM_STRATEGY_BRIEF_JSON
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_strategy_brief(dataset), indent=2), encoding="utf-8")
    return target


def run_fetch(
    *,
    account: str = config.INSTAGRAM_ACCOUNT,
    limit: int = 50,
    include_comments: bool = False,
) -> dict[str, Any]:
    return fetch_posts(account=account, limit=limit, include_comments=include_comments)


def run_export() -> dict[str, Any]:
    dataset = build_dataset()
    dataset_path = write_dataset(dataset)
    brief_path = write_strategy_brief(dataset)
    return {
        "account": dataset.account,
        "posts": len(dataset.posts),
        "dataset": str(dataset_path),
        "strategy_brief": str(brief_path),
    }


def run_sync_supabase(*, dry_run: bool = False, skip_embed: bool = False) -> dict[str, int]:
    if not config.INSTAGRAM_DATASET_JSON.exists():
        run_export()
    return run_sync(dry_run=dry_run, skip_embed=skip_embed)

