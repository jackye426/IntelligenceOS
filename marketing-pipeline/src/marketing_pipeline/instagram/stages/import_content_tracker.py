"""Import and match Instagram rows from the historical content tracker CSV."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from marketing_pipeline import config


def shortcode_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = [p for p in url.strip().split("/") if p]
    for marker in ("p", "reel", "reels"):
        if marker in parts:
            idx = parts.index(marker)
            if idx + 1 < len(parts):
                return parts[idx + 1]
    return None


def _pick(row: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = row.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _num(row: dict[str, str], column: str) -> int | float | None:
    value = row.get(column)
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return None


def _row_metrics(row: dict[str, str]) -> dict[str, Any]:
    mapping = {
        "views": "IG_Views",
        "reach": "IG_Reach",
        "likes": "IG_Likes",
        "comments": "IG_Comments",
        "saves": "IG_Saves",
        "shares": "IG_Shares",
        "profile_visits": "IG_Profile_Visits",
        "follows": "IG_Follows",
        "follows_attributed": "IG_Follows_Attributed",
        "external_link_taps": "IG_External_Link_Tap",
        "avg_watch_time_sec": "Avg Watch Time(sec)",
        "skip_rate": "Skip Rate",
    }
    metrics: dict[str, Any] = {}
    for key, column in mapping.items():
        parsed = _num(row, column)
        if parsed is not None:
            metrics[key] = parsed
    return metrics


def load_tracker_rows(path: Path | None = None) -> dict[str, dict[str, Any]]:
    target = path or config.INSTAGRAM_CONTENT_TRACKER_CSV
    if not target.exists():
        return {}

    rows: dict[str, dict[str, Any]] = {}
    with target.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            permalink = _pick(row, "IG_Permalink")
            shortcode = shortcode_from_url(permalink)
            post_id = _pick(row, "IG_Post_ID")
            keys = [k for k in (shortcode, post_id, permalink) if k]
            if not keys:
                continue
            payload = {
                "source": "content_tracker_csv",
                "asset_id": _pick(row, "Asset_ID"),
                "post_id": post_id,
                "permalink": permalink,
                "shortcode": shortcode,
                "publish_date": _pick(row, "Publish_Date", "IG_Publish_Time"),
                "topic": _pick(row, "Topic"),
                "caption": _pick(row, "Caption"),
                "format": _pick(row, "Asset type", "Content_Bucket"),
                "content_bucket": _pick(row, "Content_Bucket"),
                "post_objective": _pick(row, "Post_Objective"),
                "featured_person": _pick(row, "Featured_Person"),
                "hook_cover_text": _pick(row, "Hook_Cover_Text"),
                "caption_opening_line": _pick(row, "Caption_Opening_Line"),
                "cta": _pick(row, "CTA"),
                "main_learning": _pick(row, "Main_Learning"),
                "metrics": _row_metrics(row),
            }
            for key in keys:
                rows[str(key)] = payload
    return rows

