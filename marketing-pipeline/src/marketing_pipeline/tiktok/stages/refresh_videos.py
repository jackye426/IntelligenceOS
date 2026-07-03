"""Package-native catalog stats refresh + transcribe new videos."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from marketing_pipeline import config
from marketing_pipeline.tiktok.stages.refresh_stats import load_catalog_rows, refresh_stats
from marketing_pipeline.tiktok.stages.transcribe_video import transcribe_video
from marketing_pipeline.tiktok.stages.write_per_video_complete import existing_complete_ids
from marketing_pipeline.tiktok.stages.yt_meta import fetch_yt_meta


def refresh_videos(
    *,
    since: str = "2026-04-20",
    skip_transcribe: bool = False,
    whisper_model: str | None = None,
    download_if_missing: bool = True,
) -> dict:
    catalog = load_catalog_rows(since=since)
    have = existing_complete_ids()
    need_transcribe = [row for row in catalog if row["video_id"] not in have]

    stats_result = refresh_stats(catalog, have_complete=have)
    transcribe_log: list[dict] = []

    if not skip_transcribe and need_transcribe:
        for row in need_transcribe:
            video_id = row["video_id"]
            try:
                meta = fetch_yt_meta(video_id)
            except Exception as exc:  # noqa: BLE001
                transcribe_log.append({"video_id": video_id, "status": "meta_failed", "error": str(exc)})
                continue
            result = transcribe_video(
                video_id,
                meta,
                model_size=whisper_model,
                download_if_missing=download_if_missing,
            )
            transcribe_log.append(result)
            if result.get("status") == "transcribed":
                have.add(video_id)

    slug = since.replace("-", "")
    missing = [row for row in catalog if row["video_id"] not in have]
    miss_path = config.ANALYSIS_DIR / f"docmap_no_transcript_since_{slug}.csv"
    if missing:
        config.ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
        with miss_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(missing[0].keys()))
            writer.writeheader()
            writer.writerows(missing)
    elif miss_path.exists():
        miss_path.unlink()

    # Update has_complete flags on metrics file
    metrics_path = Path(stats_result["metrics_path"])
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        for item in metrics:
            if "video_id" in item:
                item["has_complete_transcript"] = item["video_id"] in have
        metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    log_path = config.ANALYSIS_DIR / "refresh_transcribe_log.json"
    log_path.write_text(
        json.dumps(
            {
                "refreshed_at": datetime.now(timezone.utc).isoformat(),
                "since": since,
                "catalog_count": len(catalog),
                "already_had_transcript": len(catalog) - len(need_transcribe),
                "attempted_new": len(need_transcribe),
                "results": transcribe_log,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "since": since,
        "catalog_count": len(catalog),
        "with_transcript": len(have),
        "newly_attempted": len(need_transcribe),
        "transcribe_log": transcribe_log,
        "stats": stats_result,
        "log_path": str(log_path),
    }
