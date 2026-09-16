"""Peer ingest handler: parent never activate_account; child is a subprocess."""

from __future__ import annotations

import inspect
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from marketing_pipeline import config
from marketing_pipeline.creators.paths import normalise_handle
from marketing_pipeline.creators.store import get_store

AUTO_SAMPLE = 80
ON_DEMAND_SAMPLE = 200


def ingest_argv(handle: str, *, quality: str = "auto") -> list[list[str]]:
    """Commands the child process runs. Always includes --skip-embed on sync."""
    handle = normalise_handle(handle)
    deep = ON_DEMAND_SAMPLE if quality == "on_demand" else AUTO_SAMPLE
    skip_ocr = quality != "on_demand"
    refresh = [
        sys.executable,
        "-m",
        "marketing_pipeline",
        "tiktok",
        "--account",
        handle,
        "refresh",
        "--skip-comments",
        "--skip-catalog",
    ]
    if skip_ocr:
        refresh.append("--skip-ocr")
    return [
        [
            sys.executable,
            "-m",
            "marketing_pipeline",
            "tiktok",
            "--account",
            handle,
            "fetch-catalog",
        ],
        [
            sys.executable,
            "-m",
            "marketing_pipeline",
            "tiktok",
            "--account",
            handle,
            "sample-plan",
            "--deep",
            str(deep),
        ],
        refresh,
        [
            sys.executable,
            "-m",
            "marketing_pipeline",
            "tiktok",
            "--account",
            handle,
            "extract-components",
            "--from-sample-plan",
        ],
        [
            sys.executable,
            "-m",
            "marketing_pipeline",
            "tiktok",
            "--account",
            handle,
            "sync-supabase",
            "--skip-embed",
        ],
    ]


def peer_media_dir(handle: str) -> Path:
    return config.peer_data_root(normalise_handle(handle)) / "media"


def peer_transcripts_dir(handle: str) -> Path:
    return config.peer_data_root(normalise_handle(handle)) / "transcripts"


def delete_peer_media(handle: str) -> dict[str, Any]:
    """Remove downloaded media after Whisper/OCR. Transcripts stay."""
    media = peer_media_dir(handle)
    transcripts = peer_transcripts_dir(handle)
    existed = media.exists()
    if existed:
        shutil.rmtree(media, ignore_errors=True)
    media.mkdir(parents=True, exist_ok=True)
    return {
        "media_dir": str(media),
        "deleted": existed,
        "transcripts_kept": transcripts.exists(),
        "media_empty": not any(media.iterdir()) if media.exists() else True,
    }


def parent_forbids_activate_account() -> bool:
    """Guard used by tests: this module must not call activate_account."""
    source = inspect.getsource(run_promote_peer)
    return "activate_account(" not in source and "config.activate_account" not in source


def run_promote_peer(
    handle: str,
    *,
    quality: str = "auto",
    dry_run: bool = False,
    runner: Any | None = None,
) -> dict[str, Any]:
    """Fork the TikTok ingest. Parent ACCOUNT is unchanged."""
    handle = normalise_handle(handle)
    if quality not in {"auto", "on_demand"}:
        raise ValueError("quality must be auto or on_demand")
    commands = ingest_argv(handle, quality=quality)
    parent_account = getattr(config, "ACCOUNT", "docmap")
    steps: list[dict[str, Any]] = []
    if dry_run:
        return {
            "handle": handle,
            "quality": quality,
            "dry_run": True,
            "parent_account": parent_account,
            "commands": commands,
            "skip_embed": True,
        }

    run = runner or subprocess.run
    for argv in commands:
        completed = run(argv, check=False, capture_output=True, text=True)
        code = getattr(completed, "returncode", 0)
        steps.append({"argv": argv, "returncode": code})
        if code != 0:
            return {
                "handle": handle,
                "quality": quality,
                "status": "failed",
                "parent_account": getattr(config, "ACCOUNT", parent_account),
                "steps": steps,
                "skip_embed": True,
            }

    media = delete_peer_media(handle)
    store = get_store()
    profile = store.get("creator_profiles", handle=handle)
    if profile:
        store.update(
            "creator_profiles",
            {
                "deep_status": "ingested",
                "deep_quality": quality,
                "peer_account_handle": handle,
            },
            id=profile["id"],
        )
        from marketing_pipeline.creators.enqueue_deep import _open_job

        job = _open_job("write_brief", store)
        store.upsert(
            "creator_deep_job_items",
            {
                "job_id": job["id"],
                "kind": "write_brief",
                "item_key": profile["id"],
                "priority": 80 if quality == "auto" else 100,
                "payload": {"handle": handle, "quality": quality},
                "status": "queued",
            },
            keys=("kind", "item_key"),
        )
    return {
        "handle": handle,
        "quality": quality,
        "status": "completed",
        "parent_account": getattr(config, "ACCOUNT", parent_account),
        "steps": steps,
        "media": media,
        "skip_embed": True,
    }
