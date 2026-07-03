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
    slug = since.replace("-", "")
    path = config.CATALOG_DIR / f"docmap_catalog_since_{slug}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return list(load_catalog(config.CATALOG_DIR).values())


def refresh_stats(
    catalog: list[dict],
    *,
    have_complete: set[str] | None = None,
) -> dict:
    have = have_complete if have_complete is not None else existing_complete_ids()
    metrics: list[dict] = []
    for row in catalog:
        video_id = row["video_id"]
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
