"""Ingest the marketing content tracker CSV into content_posts + embeddings."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from common import config
from common.embeddings import upsert_embedding_chunks
from common.ingestion_log import finish_run, start_run
from common.supabase_client import get_client

JOB_NAME = "content_tracker_instagram"


def _pick(row: pd.Series, *names: str) -> str | None:
    for name in names:
        if name in row.index:
            value = row[name]
            if pd.notna(value) and str(value).strip():
                return str(value).strip()
    return None


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).isoformat()
        except ValueError:
            continue
    return None


def _metric_value(row: pd.Series, column: str) -> int | float | None:
    if column not in row.index:
        return None
    value = row[column]
    if pd.isna(value):
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return None


def _build_instagram_metrics(row: pd.Series) -> dict[str, Any]:
    """Canonical metrics for Instagram-only rows (kept separate from TikTok)."""
    mapping = {
        "views": "IG_Views",
        "reach": "IG_Reach",
        "likes": "IG_Likes",
        "comments": "IG_Comments",
        "saves": "IG_Saves",
        "shares": "IG_Shares",
    }
    metrics: dict[str, Any] = {}
    for canonical, column in mapping.items():
        parsed = _metric_value(row, column)
        if parsed is not None:
            metrics[canonical] = parsed
    return metrics


def _derive_title(row: pd.Series, topic: str | None) -> str | None:
    title = _pick(row, "Topic", "Caption_Opening_Line", "Caption")
    if title:
        return title
    return topic


def _build_embedding_text(row: dict[str, Any]) -> str:
    parts = [
        f"Topic: {row['topic']}" if row.get("topic") else None,
        f"Title: {row['title']}" if row.get("title") else None,
        f"Hook: {row['hook']}" if row.get("hook") else None,
        f"Caption: {row['caption']}" if row.get("caption") else None,
        f"Transcript: {row['transcript']}" if row.get("transcript") else None,
        f"Learning: {row['metadata'].get('main_learning')}"
        if row.get("metadata", {}).get("main_learning")
        else None,
    ]
    return "\n\n".join(part for part in parts if part)


def _row_to_payload(row: pd.Series) -> dict[str, Any] | None:
    # Instagram-only lane — TikTok is ingested from ALL_COMPLETE_TRANSCRIPTS.txt.
    post_url = _pick(row, "IG_Permalink")
    if not post_url:
        return None

    asset_id = _pick(row, "Asset_ID", "IG_Post_ID")
    platform_post_id = _pick(row, "IG_Post_ID") or f"asset-{asset_id or 'unknown'}"

    topic = _pick(row, "Topic")
    title = _derive_title(row, topic)
    posted_at = _parse_date(_pick(row, "Publish_Date", "IG_Publish_Time"))

    payload = {
        "platform": "instagram",
        "platform_post_id": platform_post_id,
        "title": title,
        "post_url": post_url,
        "posted_at": posted_at,
        "topic": topic,
        "format": _pick(row, "Asset type", "Content_Bucket"),
        "hook": _pick(row, "Hook_Cover_Text", "Caption_Opening_Line"),
        "caption": _pick(row, "Caption"),
        "transcript": None,
        "metrics": _build_instagram_metrics(row),
        "metadata": {
            "source": "content_tracker_csv",
            "asset_id": asset_id,
            "post_objective": _pick(row, "Post_Objective"),
            "featured_person": _pick(row, "Featured_Person"),
            "main_learning": _pick(row, "Main_Learning"),
            "content_bucket": _pick(row, "Content_Bucket"),
        },
    }
    return payload


def run_content_tracker(csv_path: str | None = None) -> dict[str, int]:
    path = csv_path or str(config.CONTENT_TRACKER_CSV)
    run_id = start_run(JOB_NAME, {"csv_path": path})
    counts = {"rows_seen": 0, "rows_inserted": 0, "rows_updated": 0}
    client = get_client()

    try:
        frame = pd.read_csv(path)
        counts["rows_seen"] = len(frame)

        for _, row in frame.iterrows():
            payload = _row_to_payload(row)
            if not payload:
                continue

            existing = (
                client.table("content_posts")
                .select("id")
                .eq("platform", payload["platform"])
                .eq("platform_post_id", payload["platform_post_id"])
                .limit(1)
                .execute()
            )

            if existing.data:
                post_id = existing.data[0]["id"]
                client.table("content_posts").update(payload).eq("id", post_id).execute()
                counts["rows_updated"] += 1
            else:
                inserted = client.table("content_posts").insert(payload).execute()
                post_id = inserted.data[0]["id"]
                counts["rows_inserted"] += 1

            embedding_text = _build_embedding_text({**payload, "id": post_id})
            if embedding_text.strip():
                upsert_embedding_chunks(
                    entity_type="content_post",
                    entity_id=post_id,
                    text=embedding_text,
                    source_table="content_posts",
                    source_title=payload.get("title"),
                    source_url=payload.get("post_url"),
                    metadata={
                        "platform": payload["platform"],
                        "topic": payload.get("topic"),
                    },
                )

        finish_run(run_id, "success", counts)
        return counts
    except Exception as exc:  # noqa: BLE001
        finish_run(run_id, "failed", counts, error=str(exc))
        raise
