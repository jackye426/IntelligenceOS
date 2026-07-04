"""CLI entrypoint for ingestion-pipeline."""

from __future__ import annotations

import argparse
import json
import logging

from ingestion_pipeline import config


def _review_parser(sub: argparse._SubParsersAction) -> None:
    review = sub.add_parser("review", help="Human review queue")
    review_sub = review.add_subparsers(dest="command", required=True)
    review_sub.add_parser("list", help="List pending review records")
    for action in ("approve", "reject"):
        p = review_sub.add_parser(action, help=f"{action.capitalize()} a pending record")
        p.add_argument("source_id")


def _sync_parser(sub: argparse._SubParsersAction) -> None:
    sync = sub.add_parser("sync", help="Sync staged records to Supabase")
    sync_sub = sync.add_subparsers(dest="command", required=True)

    clinic = sync_sub.add_parser("clinic-csv", help="P4: seed clinic_accounts from sales CSV")
    clinic.add_argument("--csv", default=str(config.CLINIC_SALES_CSV_PATH))
    clinic.add_argument("--dry-run", action="store_true")
    clinic.add_argument("--skip-embed", action="store_true")
    clinic.add_argument("--include-filtered", action="store_true",
                        help="Also import rows the sales agent pre-filtered (hospitals/NHS)")
    clinic.add_argument("--limit", type=int, default=None)

    sync_all = sync_sub.add_parser("all", help="Run every shipped lane")
    sync_all.add_argument("--dry-run", action="store_true")


def _run_clinic_csv(args: argparse.Namespace) -> dict:
    from pathlib import Path

    from ingestion_pipeline.lanes.clinic_csv.parse import LANE, parse_clinic_csv
    from ingestion_pipeline.staging import stage_records
    from ingestion_pipeline.sync.clinic_accounts import sync_clinic_accounts

    records = parse_clinic_csv(
        Path(args.csv),
        include_filtered=args.include_filtered,
        limit=args.limit,
    )
    staged = stage_records(LANE, records)
    synced = sync_clinic_accounts(
        records, dry_run=args.dry_run, skip_embed=args.skip_embed
    )
    return {"lane": LANE, "staged": staged, "synced": synced, "dry_run": args.dry_run}


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(prog="ingestion_pipeline")
    sub = parser.add_subparsers(dest="group", required=True)
    _review_parser(sub)
    _sync_parser(sub)

    args = parser.parse_args(argv)

    if args.group == "review":
        from ingestion_pipeline import review

        if args.command == "list":
            pending = review.list_pending()
            for record in pending:
                print(f"{record.lane}\t{record.source_id}\t{record.source_title or ''}")
            print(f"{len(pending)} pending")
            return
        record = review.approve(args.source_id) if args.command == "approve" else review.reject(args.source_id)
        print(f"{args.command}d: {record.source_id} (lane={record.lane})")
        return

    if args.group == "sync":
        if args.command == "clinic-csv":
            result = _run_clinic_csv(args)
        elif args.command == "all":
            # One entry per shipped lane; extend as P1-P3 land.
            clinic_args = argparse.Namespace(
                csv=str(config.CLINIC_SALES_CSV_PATH),
                dry_run=args.dry_run,
                skip_embed=False,
                include_filtered=False,
                limit=None,
            )
            result = {"lanes": [_run_clinic_csv(clinic_args)]}
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
