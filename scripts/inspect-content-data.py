#!/usr/bin/env python3
"""Inspect content_posts quality for LLM/MCP use."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data-worker"
sys.path.insert(0, str(ROOT))

from common.supabase_client import get_client  # noqa: E402


def main() -> None:
    client = get_client()

    posts = (
        client.table("content_posts")
        .select(
            "id, platform, platform_post_id, title, post_url, posted_at, "
            "topic, format, hook, caption, transcript, metrics, metadata"
        )
        .execute()
        .data
        or []
    )

    embeddings = (
        client.table("document_embeddings")
        .select("entity_type, entity_id, source_title, chunk_index, content")
        .in_("entity_type", ["content_post", "tiktok_transcript", "tiktok_comment_batch"])
        .limit(500)
        .execute()
        .data
        or []
    )

    print("=== SUMMARY ===")
    print(f"content_posts rows: {len(posts)}")
    print(f"platforms: {dict(Counter(p.get('platform') for p in posts))}")

    def filled(field: str) -> int:
        return sum(1 for p in posts if p.get(field) and str(p.get(field)).strip())

    fields = ["title", "topic", "format", "hook", "caption", "transcript", "post_url", "posted_at"]
    print("\n=== FIELD COVERAGE ===")
    for f in fields:
        print(f"  {f}: {filled(f)}/{len(posts)} ({100*filled(f)//max(len(posts),1)}%)")

    def has_metric(p: dict, *keys: str) -> bool:
        m = p.get("metrics") or {}
        return any(isinstance(m.get(k), (int, float)) and m.get(k) for k in keys)

    with_views = sum(1 for p in posts if has_metric(p, "views", "ig_views", "tt_views"))
    with_likes = sum(1 for p in posts if has_metric(p, "likes", "ig_likes", "tt_likes"))
    empty_metrics = sum(1 for p in posts if not (p.get("metrics") or {}))

    print("\n=== METRICS ===")
    print(f"  rows with view counts: {with_views}/{len(posts)}")
    print(f"  rows with like counts: {with_likes}/{len(posts)}")
    print(f"  rows with empty metrics: {empty_metrics}/{len(posts)}")

    metric_keys = Counter()
    for p in posts:
        for k in (p.get("metrics") or {}):
            metric_keys[k] += 1
    print(f"  metric keys seen: {dict(metric_keys)}")

    print("\n=== SAMPLE ROWS (top 5 by views) ===")

    def view_score(p: dict) -> float:
        m = p.get("metrics") or {}
        for k in ("tt_views", "ig_views", "views"):
            v = m.get(k)
            if isinstance(v, (int, float)):
                return float(v)
        return 0.0

    top = sorted(posts, key=view_score, reverse=True)[:5]
    for i, p in enumerate(top, 1):
        sample = {
            "platform": p.get("platform"),
            "title": (p.get("title") or "")[:80],
            "topic": (p.get("topic") or "")[:60],
            "format": p.get("format"),
            "hook": (p.get("hook") or "")[:60] or None,
            "posted_at": p.get("posted_at"),
            "metrics": p.get("metrics"),
            "has_caption": bool(p.get("caption")),
            "has_transcript": bool(p.get("transcript")),
            "post_url": (p.get("post_url") or "")[:70],
        }
        print(f"\n--- #{i} ---")
        print(json.dumps(sample, indent=2, default=str))

    print("\n=== SPARSE / LOW-QUALITY EXAMPLES (up to 3) ===")
    sparse = [
        p
        for p in posts
        if not p.get("title")
        and not p.get("topic")
        and not p.get("caption")
        and view_score(p) == 0
    ][:3]
    for p in sparse:
        print(
            json.dumps(
                {
                    "platform": p.get("platform"),
                    "platform_post_id": p.get("platform_post_id"),
                    "metrics": p.get("metrics"),
                    "metadata": p.get("metadata"),
                },
                default=str,
            )
        )

    print("\n=== EMBEDDINGS ===")
    emb_types = Counter(e.get("entity_type") for e in embeddings)
    print(f"embedding chunks sampled: {len(embeddings)}")
    print(f"by type: {dict(emb_types)}")
    if embeddings:
        ex = embeddings[0]
        print(f"sample chunk length: {len(ex.get('content') or '')} chars")
        print(f"sample preview: {(ex.get('content') or '')[:200]}...")

    runs = (
        client.table("data_ingestion_runs")
        .select("job_name, status, rows_seen, rows_inserted, rows_updated, started_at")
        .order("started_at", desc=True)
        .limit(5)
        .execute()
        .data
        or []
    )
    print("\n=== RECENT INGESTION RUNS ===")
    for r in runs:
        print(
            f"  {r.get('started_at')} | {r.get('job_name')} | {r.get('status')} | "
            f"seen={r.get('rows_seen')} ins={r.get('rows_inserted')} upd={r.get('rows_updated')}"
        )


if __name__ == "__main__":
    main()
