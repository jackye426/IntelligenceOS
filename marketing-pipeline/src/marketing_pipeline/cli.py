"""CLI entrypoint for marketing-pipeline."""

from __future__ import annotations

import argparse
import json
import sys

from marketing_pipeline.tiktok.orchestrator import (
    run_analyze,
    run_display_snapshots,
    run_export,
    run_fetch_catalog_cmd,
    run_fetch_comments_cmd,
    run_sample_plan_cmd,
    run_extract_components_cmd,
    run_import_playbooks,
    run_ingest_bc_csv,
    run_ingest_studio_insight,
    run_ocr_batch,
    run_refresh,
    run_refresh_comments,
    run_studio_listen,
    run_sync_playbooks_cmd,
    run_sync_supabase,
)
from marketing_pipeline.instagram.orchestrator import (
    run_export as run_instagram_export,
    run_fetch as run_instagram_fetch,
    run_login as run_instagram_login,
    run_sync_supabase as run_instagram_sync_supabase,
)


# Peer commands must name their account explicitly. Defaulting to docmap would
# let a peer run write into the owned library.
PEER_SAFE_DEFAULT = "docmap"


def _tiktok_parser(sub: argparse._SubParsersAction) -> None:
    tiktok = sub.add_parser("tiktok", help="TikTok marketing pipeline")
    tiktok.add_argument(
        "--account",
        default=PEER_SAFE_DEFAULT,
        help="Account handle to operate on (default docmap). Any other value is a "
        "peer library with its own data root, prompts and Supabase scope.",
    )
    tiktok_sub = tiktok.add_subparsers(dest="command", required=True)

    fetch_cat = tiktok_sub.add_parser(
        "fetch-catalog",
        help="Fetch profile catalog + follower count + bio (cheap; run before sample-plan)",
    )
    fetch_cat.add_argument("--since", default="2019-01-01")
    fetch_cat.add_argument("--cookies-from-browser", default=None)

    sample = tiktok_sub.add_parser(
        "sample-plan",
        help="Detect eras and pick a reproducible stratified deep sample",
    )
    sample.add_argument("--deep", type=int, default=200, help="Target deep-sample size")
    sample.add_argument("--seed", type=int, default=20260910)
    sample.add_argument("--since", default=None)

    fetch_comments = tiktok_sub.add_parser(
        "fetch-comments",
        help="Optional comment drill-down for named videos (budgeted, resumable)",
    )
    fetch_comments.add_argument(
        "--video-id", action="append", dest="video_ids", default=None, help="Repeatable"
    )
    fetch_comments.add_argument("--max-comments", type=int, default=500)
    fetch_comments.add_argument("--request-budget", type=int, default=400)
    fetch_comments.add_argument("--force", action="store_true")

    tiktok_sub.add_parser("export", help="Build dataset JSON from local artifacts")
    tiktok_sub.add_parser("analyze", help="Run analysis and write dataset")
    tiktok_sub.add_parser("import-playbooks", help="Import strategy docs into playbooks/")

    refresh = tiktok_sub.add_parser("refresh", help="Catalog refresh + OCR + comments + export")
    refresh.add_argument("--since", default="2026-04-20")
    refresh.add_argument("--skip-transcribe", action="store_true")
    refresh.add_argument("--skip-ocr", action="store_true")
    refresh.add_argument("--skip-comments", action="store_true")
    refresh.add_argument("--no-download", action="store_true", help="Skip yt-dlp media download for OCR only")
    refresh.add_argument(
        "--skip-catalog",
        action="store_true",
        help="Reuse the catalog on disk instead of re-listing the profile (use when resuming)",
    )

    refresh_comments = tiktok_sub.add_parser("refresh-comments", help="Fetch, label, compile comments")
    refresh_comments.add_argument("--force", action="store_true")

    ocr = tiktok_sub.add_parser("ocr-hooks", help="Run on-screen hook OCR for catalog videos")
    ocr.add_argument("--force", action="store_true")
    ocr.add_argument("--no-download", action="store_true")

    extract_comp = tiktok_sub.add_parser(
        "extract-components",
        help="Batch LLM extract of video components (hook/funnel/CTA/…); writes analysis sidecars",
    )
    extract_comp.add_argument("--video-id", default=None)
    extract_comp.add_argument("--force", action="store_true")
    extract_comp.add_argument("--limit", type=int, default=None)
    extract_comp.add_argument(
        "--schema",
        default=None,
        choices=["docmap-endo", "generic-clinician"],
        help="Component prompt schema. Peer accounts default to generic-clinician.",
    )
    extract_comp.add_argument(
        "--from-sample-plan",
        action="store_true",
        dest="sample_only",
        help="Restrict to the deep sample recorded in sample_plan.json",
    )

    sync = tiktok_sub.add_parser("sync-supabase", help="Sync dataset to Supabase")
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument("--skip-embed", action="store_true")

    sync_pb = tiktok_sub.add_parser("sync-playbooks", help="Embed playbooks + comment digest")
    sync_pb.add_argument("--dry-run", action="store_true")
    sync_pb.add_argument("--skip-embed", action="store_true")

    display = tiktok_sub.add_parser(
        "display-snapshots",
        help="Poll TikTok Display API and append metric snapshots (velocity layer)",
    )
    display.add_argument("--dry-run", action="store_true")
    display.add_argument(
        "--no-update-latest",
        action="store_true",
        help="Do not merge views/likes/comments/shares into content_posts.metrics",
    )
    display.add_argument(
        "--video-id",
        action="append",
        dest="video_ids",
        default=None,
        help="Limit to specific video id(s); repeatable",
    )

    studio = tiktok_sub.add_parser(
        "ingest-studio-insight",
        help="Ingest Studio /aweme/v2/data/insight/ JSON (file or directory)",
    )
    studio.add_argument("path", help="Insight JSON file or directory of *.json")
    studio.add_argument("--video-id", default=None, help="Override video id when not in payload")
    studio.add_argument("--dry-run", action="store_true")

    bc = tiktok_sub.add_parser(
        "ingest-bc-csv",
        help="Ingest Business Center Overview + Followers CSV export folder",
    )
    bc.add_argument(
        "directory",
        nargs="?",
        default=None,
        help="Export folder (default: MARKETING_DATA_DIR/imports/business_center)",
    )
    bc.add_argument("--account", default="docmap")
    bc.add_argument("--dry-run", action="store_true")

    studio_listen = tiktok_sub.add_parser(
        "studio-listen",
        help="Playwright: capture Studio /aweme/v2/data/insight/ (login once, then poll videos)",
    )
    studio_listen.add_argument(
        "--login",
        action="store_true",
        help="Open headed browser to log into TikTok Studio (saves persistent profile)",
    )
    studio_listen.add_argument("--video-id", action="append", dest="video_ids", default=None)
    studio_listen.add_argument(
        "--recent",
        type=int,
        default=None,
        help="Capture N newest catalog videos (default 15 for incremental)",
    )
    studio_listen.add_argument(
        "--all",
        action="store_true",
        dest="all_videos",
        help="One-time full catalog baseline (~71 videos; slow pauses; no recent cap)",
    )
    studio_listen.add_argument(
        "--headed",
        action="store_true",
        help="Show browser (default headless for capture; --login is always headed)",
    )
    studio_listen.add_argument(
        "--ingest",
        action="store_true",
        help="Upsert captured insights into tiktok_studio_insights",
    )
    studio_listen.add_argument("--dry-run", action="store_true")


def _instagram_parser(sub: argparse._SubParsersAction) -> None:
    instagram = sub.add_parser("instagram", help="Instagram marketing pipeline")
    instagram_sub = instagram.add_subparsers(dest="command", required=True)

    login = instagram_sub.add_parser(
        "login",
        help="Create Instaloader session file (session-docmapuk) for fetch + Railway",
    )
    login.add_argument("--account", default="docmapuk", help="Instagram username to log in as")
    login.add_argument(
        "--password",
        default=None,
        help="Optional; omit to type password / 2FA interactively (safer)",
    )

    fetch = instagram_sub.add_parser(
        "fetch",
        help="Fetch recent Instagram posts for docmapuk via Instaloader (requires session)",
    )
    fetch.add_argument("--account", default="docmapuk")
    fetch.add_argument("--limit", type=int, default=50)
    fetch.add_argument("--include-comments", action="store_true")

    instagram_sub.add_parser(
        "export",
        help="Build Instagram dataset JSON from local raw artifacts + content tracker enrichment",
    )

    sync = instagram_sub.add_parser("sync-supabase", help="Sync Instagram dataset to Supabase")
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument("--skip-embed", action="store_true")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="marketing_pipeline")
    sub = parser.add_subparsers(dest="channel", required=True)
    _tiktok_parser(sub)
    _instagram_parser(sub)

    args = parser.parse_args(argv)
    if args.channel not in {"tiktok", "instagram"}:
        parser.error(f"Unsupported channel: {args.channel}")

    if args.channel == "tiktok":
        # Point every path constant at this account before any stage runs.
        from marketing_pipeline import config

        try:
            active = config.activate_account(getattr(args, "account", None))
        except config.AccountIsolationError as exc:
            parser.error(str(exc))
        if config.is_peer_account(active):
            # Owner-only surfaces: Studio, Display API and Business Center all
            # require authenticated access to the account. They cannot work on a
            # peer, and playbooks/insights are DocMap governance artefacts.
            owner_only = {
                "display-snapshots",
                "ingest-studio-insight",
                "studio-listen",
                "ingest-bc-csv",
                "sync-playbooks",
                "import-playbooks",
            }
            if args.command in owner_only:
                parser.error(
                    f"'{args.command}' is owner-only and cannot run for peer account "
                    f"'{active}'. It needs authenticated access to the account, or it "
                    "writes DocMap governance artefacts."
                )
            print(
                json.dumps(
                    {
                        "account": active,
                        "mode": "peer_library",
                        "data_root": str(config.DATA_ROOT),
                        "owner_scope": config.owner_scope(),
                        "note": "Peer run: isolated data root, generic prompts, "
                        "no strategy brief, comments off by default.",
                    },
                    indent=2,
                ),
                file=sys.stderr,
            )

    if args.channel == "instagram":
        if args.command == "login":
            result = run_instagram_login(account=args.account, password=args.password)
        elif args.command == "fetch":
            result = run_instagram_fetch(
                account=args.account,
                limit=args.limit,
                include_comments=args.include_comments,
            )
        elif args.command == "export":
            result = run_instagram_export()
        elif args.command == "sync-supabase":
            result = run_instagram_sync_supabase(
                dry_run=args.dry_run,
                skip_embed=args.skip_embed,
            )
        else:
            parser.error(f"Unknown Instagram command: {args.command}")
        print(json.dumps(result, indent=2, default=str))
        return

    if args.command == "fetch-catalog":
        result = run_fetch_catalog_cmd(
            since=args.since,
            cookies_from_browser=args.cookies_from_browser,
        )
    elif args.command == "sample-plan":
        result = run_sample_plan_cmd(deep=args.deep, seed=args.seed, since=args.since)
    elif args.command == "fetch-comments":
        result = run_fetch_comments_cmd(
            video_ids=args.video_ids,
            max_comments=args.max_comments,
            request_budget=args.request_budget,
            force=args.force,
        )
    elif args.command == "export":
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
            skip_catalog=args.skip_catalog,
        )
    elif args.command == "refresh-comments":
        result = run_refresh_comments(force=args.force)
    elif args.command == "ocr-hooks":
        result = run_ocr_batch(
            download_if_missing=not args.no_download,
            force=args.force,
        )
    elif args.command == "extract-components":
        result = run_extract_components_cmd(
            video_id=args.video_id,
            force=args.force,
            limit=args.limit,
            schema=args.schema,
            sample_only=args.sample_only,
        )
    elif args.command == "sync-supabase":
        result = run_sync_supabase(dry_run=args.dry_run, skip_embed=args.skip_embed)
    elif args.command == "sync-playbooks":
        result = run_sync_playbooks_cmd(dry_run=args.dry_run, skip_embed=args.skip_embed)
    elif args.command == "display-snapshots":
        result = run_display_snapshots(
            video_ids=args.video_ids,
            update_latest=not args.no_update_latest,
            dry_run=args.dry_run,
        )
    elif args.command == "ingest-studio-insight":
        result = run_ingest_studio_insight(
            args.path,
            video_id=args.video_id,
            dry_run=args.dry_run,
        )
    elif args.command == "ingest-bc-csv":
        result = run_ingest_bc_csv(
            args.directory,
            account_handle=args.account,
            dry_run=args.dry_run,
        )
    elif args.command == "studio-listen":
        result = run_studio_listen(
            login=args.login,
            video_ids=args.video_ids,
            recent=args.recent,
            all_videos=args.all_videos,
            headless=not args.headed and not args.login,
            ingest=args.ingest,
            dry_run=args.dry_run,
        )
    else:
        parser.error(f"Unknown command: {args.command}")
        return

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
