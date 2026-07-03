"""CLI entrypoint for marketing-pipeline."""

from __future__ import annotations

import argparse
import json
import sys

from marketing_pipeline.tiktok.orchestrator import (
    run_analyze,
    run_export,
    run_import_playbooks,
    run_ocr_batch,
    run_refresh,
    run_refresh_comments,
    run_sync_playbooks_cmd,
    run_sync_supabase,
)


def _tiktok_parser(sub: argparse._SubParsersAction) -> None:
    tiktok = sub.add_parser("tiktok", help="TikTok marketing pipeline")
    tiktok_sub = tiktok.add_subparsers(dest="command", required=True)

    tiktok_sub.add_parser("export", help="Build dataset JSON from local artifacts")
    tiktok_sub.add_parser("analyze", help="Run analysis and write dataset")
    tiktok_sub.add_parser("import-playbooks", help="Import strategy docs into playbooks/")

    refresh = tiktok_sub.add_parser("refresh", help="Catalog refresh + OCR + comments + export")
    refresh.add_argument("--since", default="2026-04-20")
    refresh.add_argument("--skip-transcribe", action="store_true")
    refresh.add_argument("--skip-ocr", action="store_true")
    refresh.add_argument("--skip-comments", action="store_true")
    refresh.add_argument("--no-download", action="store_true", help="Skip yt-dlp media download for OCR only")

    refresh_comments = tiktok_sub.add_parser("refresh-comments", help="Fetch, label, compile comments")
    refresh_comments.add_argument("--force", action="store_true")

    ocr = tiktok_sub.add_parser("ocr-hooks", help="Run on-screen hook OCR for catalog videos")
    ocr.add_argument("--force", action="store_true")
    ocr.add_argument("--no-download", action="store_true")

    sync = tiktok_sub.add_parser("sync-supabase", help="Sync dataset to Supabase")
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument("--skip-embed", action="store_true")

    sync_pb = tiktok_sub.add_parser("sync-playbooks", help="Embed playbooks + comment digest")
    sync_pb.add_argument("--dry-run", action="store_true")
    sync_pb.add_argument("--skip-embed", action="store_true")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="marketing_pipeline")
    sub = parser.add_subparsers(dest="channel", required=True)
    _tiktok_parser(sub)

    args = parser.parse_args(argv)
    if args.channel != "tiktok":
        parser.error(f"Unsupported channel: {args.channel}")

    if args.command == "export":
        result = run_export()
    elif args.command == "analyze":
        result = run_analyze()
    elif args.command == "import-playbooks":
        result = run_import_playbooks()
    elif args.command == "refresh":
        result = run_refresh(
            since=args.since,
            skip_transcribe=args.skip_transcribe,
            skip_ocr=args.skip_ocr,
            skip_comments=args.skip_comments,
            download_for_ocr=not args.no_download,
        )
    elif args.command == "refresh-comments":
        result = run_refresh_comments(force=args.force)
    elif args.command == "ocr-hooks":
        result = run_ocr_batch(
            download_if_missing=not args.no_download,
            force=args.force,
        )
    elif args.command == "sync-supabase":
        result = run_sync_supabase(dry_run=args.dry_run, skip_embed=args.skip_embed)
    elif args.command == "sync-playbooks":
        result = run_sync_playbooks_cmd(dry_run=args.dry_run, skip_embed=args.skip_embed)
    else:
        parser.error(f"Unknown command: {args.command}")
        return

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
