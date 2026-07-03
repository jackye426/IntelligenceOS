"""TikTok pipeline orchestration."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from marketing_pipeline import config
from marketing_pipeline.tiktok.models import (
    TikTokMarketingDataset,
    TikTokMetrics,
    TikTokPost,
    TikTokTranscript,
    TikTokVideoRecord,
)
from marketing_pipeline.tiktok.stages.analyze_comments import (
    build_comment_analysis,
    load_labeled_comments,
)
from marketing_pipeline.tiktok.stages.collect_catalog import load_catalog
from marketing_pipeline.tiktok.stages.collect_comments import collect_comments
from marketing_pipeline.tiktok.stages.detect_ab_pairs import attach_pairs_to_videos, detect_ab_pairs
from marketing_pipeline.tiktok.stages.draft_evidence_playbook import draft_evidence_playbook
from marketing_pipeline.tiktok.stages.extract_hooks import extract_hook
from marketing_pipeline.tiktok.stages.extract_onscreen_hook import (
    extract_onscreen_hook,
    run_ocr_for_video,
)
from marketing_pipeline.tiktok.stages.fetch_catalog import fetch_catalog
from marketing_pipeline.tiktok.stages.import_playbooks import import_playbooks
from marketing_pipeline.tiktok.stages.parse_master_transcripts import parse_master_transcripts
from marketing_pipeline.tiktok.stages.rebuild_comment_analysis import rebuild_comment_analysis
from marketing_pipeline.tiktok.stages.refresh_legacy import copy_legacy_artifacts, run_legacy_refresh
from marketing_pipeline.tiktok.stages.write_comments_digest import write_comments_digest
from marketing_pipeline.tiktok.stages.write_outputs import ensure_master_transcripts, write_dataset
from marketing_pipeline.tiktok.stages.download_media import download_media, resolve_media_path
from marketing_pipeline.tiktok.sync.playbooks import sync_playbooks
from marketing_pipeline.tiktok.sync.supabase import run_sync


def build_dataset() -> TikTokMarketingDataset:
    master_path = config.MASTER_TRANSCRIPTS
    if not master_path.exists():
        raise FileNotFoundError(f"Master transcripts not found: {master_path}")

    parsed = parse_master_transcripts(master_path)
    catalog = load_catalog(config.CATALOG_DIR)
    summary_path = config.ANALYSIS_DIR / "comment_summary_by_video.json"

    dataset = TikTokMarketingDataset(
        dataset_version=config.DATASET_VERSION,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    for row in parsed:
        video_id = row["video_id"]
        cat = catalog.get(video_id, {})
        transcript_text = row.get("transcript")
        caption = row.get("caption")

        onscreen = extract_onscreen_hook(
            video_id,
            transcript=transcript_text,
            caption=caption,
        )
        ocr_cache_path = config.OCR_CACHE_DIR / f"{video_id}.json"
        format_guess = cat.get("format") or "video"
        if ocr_cache_path.exists():
            try:
                ocr_data = json.loads(ocr_cache_path.read_text(encoding="utf-8"))
                format_guess = ocr_data.get("format_guess") or format_guess
            except json.JSONDecodeError:
                pass

        hook = extract_hook(
            video_id,
            spoken_hook=row.get("spoken_hook"),
            transcript=transcript_text,
            caption=caption,
            onscreen_hook=onscreen,
        )
        comments = load_labeled_comments(config.ANALYSIS_DIR, video_id)
        comment_analysis = (
            build_comment_analysis(video_id, comments, summary_path)
            if comments
            else None
        )

        metrics_raw = row.get("metrics") or {}
        post = TikTokPost(
            video_id=video_id,
            url=row["url"],
            posted_at=row.get("posted_at"),
            caption=caption,
            duration_sec=row.get("duration_sec"),
            format_guess=format_guess,
            metrics=TikTokMetrics(**metrics_raw),
            raw_metadata={"catalog_title": cat.get("title")},
        )
        transcript_json = config.TRANSCRIPTS_DIR / f"{video_id}.json"
        segments: list = []
        whisper_model = None
        status = "transcribed" if transcript_text else "missing"
        if transcript_json.exists():
            tdata = json.loads(transcript_json.read_text(encoding="utf-8"))
            if isinstance(tdata, dict):
                segments = tdata.get("segments") or []
                whisper_model = tdata.get("model")

        transcript = TikTokTranscript(
            video_id=video_id,
            full_text=transcript_text,
            segments=segments,
            model=whisper_model,
            status=status,
        )

        dataset.videos[video_id] = TikTokVideoRecord(
            post=post,
            transcript=transcript,
            hook=hook,
            comments=comments[:40],
            comment_analysis=comment_analysis,
        )

    pairs = detect_ab_pairs(dataset)
    dataset.ab_pairs = pairs
    attach_pairs_to_videos(dataset, pairs)
    return dataset


def run_export(*, draft_evidence: bool = True) -> dict[str, str | int]:
    dataset = build_dataset()
    write_dataset(dataset, config.DATASET_JSON)
    export_master = config.EXPORTS_DIR / "ALL_COMPLETE_TRANSCRIPTS.txt"
    ensure_master_transcripts(config.MASTER_TRANSCRIPTS, export_master)
    result: dict[str, str | int] = {
        "videos": len(dataset.videos),
        "ab_pairs": len(dataset.ab_pairs),
        "dataset": str(config.DATASET_JSON),
        "onscreen_hooks": sum(1 for v in dataset.videos.values() if v.hook.onscreen_hook),
    }
    if draft_evidence:
        draft_path = draft_evidence_playbook(dataset)
        result["evidence_draft"] = str(draft_path)
    return result


def run_analyze() -> dict[str, str | int]:
    return run_export()


def run_refresh_comments(*, force: bool = False) -> dict:
    comment_counts = collect_comments(force=force)
    analysis_counts = rebuild_comment_analysis()
    digest_counts = write_comments_digest()
    return {
        "comments": comment_counts,
        "analysis": analysis_counts,
        "digest": digest_counts,
    }


def run_ocr_batch(
    video_ids: list[str] | None = None,
    *,
    download_if_missing: bool = True,
    force: bool = False,
) -> dict[str, int]:
    if video_ids is None:
        if not config.MASTER_TRANSCRIPTS.exists():
            return {"processed": 0, "with_hook": 0, "errors": 0}
        video_ids = [row["video_id"] for row in parse_master_transcripts(config.MASTER_TRANSCRIPTS)]

    counts = {"processed": 0, "with_hook": 0, "errors": 0, "skipped": 0}
    parsed = {row["video_id"]: row for row in parse_master_transcripts(config.MASTER_TRANSCRIPTS)}

    for video_id in video_ids:
        row = parsed.get(video_id, {})
        if download_if_missing and resolve_media_path(video_id) is None:
            try:
                download_media(video_id)
            except Exception:  # noqa: BLE001
                counts["errors"] += 1
                continue
        try:
            result = run_ocr_for_video(
                video_id,
                transcript=row.get("transcript"),
                caption=row.get("caption"),
                download_if_missing=False,
                force_refresh=force,
            )
            counts["processed"] += 1
            if result.get("onscreen_hook"):
                counts["with_hook"] += 1
        except Exception:  # noqa: BLE001
            counts["errors"] += 1
    return counts


def run_refresh(
    *,
    since: str = "2026-04-20",
    skip_transcribe: bool = False,
    skip_ocr: bool = False,
    skip_comments: bool = False,
    download_for_ocr: bool = True,
) -> dict:
    catalog_result = fetch_catalog(since=since)
    run_legacy_refresh(since=since, skip_transcribe=skip_transcribe, skip_catalog=True)
    copied = copy_legacy_artifacts()

    ocr_counts = {"skipped": True}
    if not skip_ocr:
        ocr_counts = run_ocr_batch(download_if_missing=download_for_ocr)

    comment_result = {}
    if not skip_comments:
        comment_result = run_refresh_comments()

    result = run_export()
    result["catalog"] = catalog_result
    result["copied"] = copied
    result["ocr"] = ocr_counts
    result["comments_pipeline"] = comment_result
    return result


def run_sync_supabase(*, dry_run: bool = False, skip_embed: bool = False) -> dict[str, int]:
    if not config.DATASET_JSON.exists():
        run_export()
    return run_sync(dry_run=dry_run, skip_embed=skip_embed)


def run_sync_playbooks_cmd(*, dry_run: bool = False, skip_embed: bool = False) -> dict[str, int]:
    return sync_playbooks(dry_run=dry_run, skip_embed=skip_embed)


def run_import_playbooks() -> dict[str, str]:
    return import_playbooks()
