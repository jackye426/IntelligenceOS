"""Refresh TikTok stats for catalog videos."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from marketing_pipeline import config
from marketing_pipeline.tiktok.stages.collect_catalog import load_catalog
from marketing_pipeline.tiktok.stages.write_per_video_complete import existing_complete_ids
from marketing_pipeline.tiktok.stages.yt_meta import fetch_yt_meta, metrics_from_meta


def load_catalog_rows(*, since: str) -> list[dict]:
    path = config.CATALOG_DIR / config.catalog_filename(since)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return list(load_catalog(config.CATALOG_DIR).values())


def _metrics_from_catalog_row(row: dict) -> dict:
    """Same shape as metrics_from_meta, built from the catalog with no network call.

    A profile listing already carries views/likes/comments/shares/saves/duration
    for every post. Re-fetching them one video at a time adds nothing and, on a
    few-hundred-post catalog, is enough traffic to get the client throttled
    before the real work (downloading and transcribing) begins.
    """

    def _int(key: str) -> int:
        value = row.get(key)
        if value is None or value == "":
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    views = _int("view_count")
    likes = _int("like_count")
    comments = _int("comment_count")
    shares = _int("share_count")
    saves = _int("save_count")
    return {
        "video_id": str(row.get("video_id") or ""),
        "post_date_utc": row.get("post_date_utc"),
        "url": row.get("url"),
        "title": row.get("title"),
        "description": row.get("description"),
        "duration_sec": float(row.get("duration_sec") or 0),
        "view_count": views,
        "like_count": likes,
        "comment_count": comments,
        "share_count": shares,
        "save_count": saves,
        "like_per_1k_views": round(1000 * likes / views, 4) if views else None,
        "comment_per_1k_views": round(1000 * comments / views, 4) if views else None,
        "share_per_1k_views": round(1000 * shares / views, 4) if views else None,
        "save_per_1k_views": round(1000 * saves / views, 4) if views else None,
        "source": "catalog",
    }


def refresh_stats(
    catalog: list[dict],
    *,
    have_complete: set[str] | None = None,
    use_catalog_only: bool | None = None,
) -> dict:
    """Write metrics_refresh.json.

    `use_catalog_only` skips the per-video yt-dlp calls. It defaults to True for
    peer libraries, whose catalog metrics are complete and freshly fetched, and
    False for the owned account, where stats are refreshed between catalog pulls.
    """
    if use_catalog_only is None:
        use_catalog_only = config.is_peer_account()
    have = have_complete if have_complete is not None else existing_complete_ids()
    metrics: list[dict] = []
    for row in catalog:
        video_id = row["video_id"]
        if use_catalog_only:
            item = _metrics_from_catalog_row(row)
        else:
            try:
                meta = fetch_yt_meta(video_id)
            except subprocess.CalledProcessError as exc:
                metrics.append({"video_id": video_id, "error": str(exc)})
                continue
            item = metrics_from_meta(meta, catalog_row=row)
        item["has_complete_transcript"] = video_id in have
        metrics.append(item)

    metrics.sort(key=lambda x: x.get("view_count") or 0, reverse=True)
    config.ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.ANALYSIS_DIR / "metrics_refresh.json"
    path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"metrics_path": str(path), "count": len(metrics)}
