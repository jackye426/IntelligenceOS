#!/usr/bin/env python3
"""CLI entrypoint for TikTok marketing pipeline sync."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    skip_embed = "--skip-embed" in sys.argv
    dry_run = "--dry-run" in sys.argv
    with_comments = "--refresh-comments" in sys.argv

    if with_comments:
        subprocess.check_call(
            [sys.executable, "-m", "marketing_pipeline", "tiktok", "refresh-comments"],
            cwd=str(REPO_ROOT),
        )

    subprocess.check_call(
        [sys.executable, "-m", "marketing_pipeline", "tiktok", "export"],
        cwd=str(REPO_ROOT),
    )
    cmd = [sys.executable, "-m", "marketing_pipeline", "tiktok", "sync-supabase"]
    if dry_run:
        cmd.append("--dry-run")
    if skip_embed:
        cmd.append("--skip-embed")
    subprocess.check_call(cmd, cwd=str(REPO_ROOT))

    pb = [sys.executable, "-m", "marketing_pipeline", "tiktok", "sync-playbooks"]
    if dry_run:
        pb.append("--dry-run")
    if skip_embed:
        pb.append("--skip-embed")
    subprocess.check_call(pb, cwd=str(REPO_ROOT))


if __name__ == "__main__":
    main()
