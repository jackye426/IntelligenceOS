"""CLI entrypoint for gtm-pipeline."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from gtm_pipeline import config


def _json_print(payload: object) -> None:
    print(json.dumps(payload, indent=2, default=str))


def _add_doctify(sub: argparse._SubParsersAction) -> None:
    doctify = sub.add_parser("doctify", help="Doctify practice extract (P0a)")
    dsub = doctify.add_subparsers(dest="command", required=True)

    extract = dsub.add_parser("extract", help="Extract a Doctify practice page")
    extract.add_argument("--url", default=config.DOCTIFY_FIXTURE_URL)
    extract.add_argument("--html", type=Path, help="Offline HTML fixture (skip Playwright)")
    extract.add_argument("--upsert", action="store_true", help="Upsert to Supabase")
    extract.add_argument(
        "--dry-run",
        action="store_true",
        help="Print upsert payload without writing (implied if no credentials)",
    )
    extract.add_argument("--headed", action="store_true", help="Run Playwright headed")
    extract.add_argument("--out", type=Path, help="Optional JSON output path")


def _add_owners(sub: argparse._SubParsersAction) -> None:
    owners = sub.add_parser("owners", help="Owner discovery from practitioners (P0a-owners)")
    osub = owners.add_subparsers(dest="command", required=True)
    scan = osub.add_parser("scan", help="Scan integrated_practitioners.about")
    scan.add_argument("--limit", type=int, default=None)
    scan.add_argument("--dry-run", action="store_true")


def _add_people(sub: argparse._SubParsersAction) -> None:
    people = sub.add_parser("people", help="Person resolve / CQC people match")
    psub = people.add_subparsers(dest="command", required=True)
    match = psub.add_parser("match-cqc", help="Match CQC RM/NI names to practitioners")
    match.add_argument("--registered-manager", default="")
    match.add_argument("--nominated-individual", default="")
    match.add_argument("--min-confidence", type=float, default=0.82)
    match.add_argument("--dry-run", action="store_true")

    enrich = psub.add_parser(
        "enrich-cqc",
        help="Batch-match CQC people on gtm_clinic_intelligence → practitioner emails",
    )
    enrich.add_argument("--limit", type=int, default=None)
    enrich.add_argument("--min-confidence", type=float, default=0.82)
    enrich.add_argument("--dry-run", action="store_true")


def _add_sync(sub: argparse._SubParsersAction) -> None:
    sync = sub.add_parser("sync", help="Supabase sync helpers")
    ssub = sync.add_subparsers(dest="command", required=True)
    scoped = ssub.add_parser("scoped-csv", help="Upsert Clinic sales scoped CSV into gtm_*")
    scoped.add_argument(
        "--path",
        type=Path,
        default=Path("gtm-pipeline/data/full_scope_run.csv"),
    )
    scoped.add_argument("--limit", type=int, default=None)
    scoped.add_argument("--dry-run", action="store_true")
    scoped.add_argument(
        "--include-pre-filtered",
        action="store_true",
        help="Also sync pre_filtered hospital rows",
    )


def _add_cqc(sub: argparse._SubParsersAction) -> None:
    cqc = sub.add_parser("cqc", help="CQC directory + location lanes (P0b)")
    csub = cqc.add_subparsers(dest="command", required=True)

    match = csub.add_parser("match", help="Match a clinic against the CQC directory")
    match.add_argument("--name", required=True)
    match.add_argument("--postcode", default="")
    match.add_argument("--address", default="")
    match.add_argument("--website", default="")
    match.add_argument("--phone", default="")
    match.add_argument("--top", type=int, default=5)

    loc = csub.add_parser("location", help="Scrape a CQC location Overview page")
    loc.add_argument(
        "--url",
        default="https://www.cqc.org.uk/location/1-19271937885",
        help="CQC location URL or ID",
    )
    loc.add_argument("--html", type=Path, help="Offline HTML fixture")
    loc.add_argument("--upsert", action="store_true")
    loc.add_argument("--dry-run", action="store_true")
    loc.add_argument("--clinic-account-id", default=None)
    loc.add_argument("--doctify-url", default=None)


def _run_doctify_extract(args: argparse.Namespace) -> dict:
    from gtm_pipeline.doctify.extract import extract_practice_sync, parse_specialists_from_html
    from gtm_pipeline.shared.supabase_client import supabase_configured
    from gtm_pipeline.sync.clinic_intelligence import sync_doctify_extract

    if args.html:
        html = args.html.read_text(encoding="utf-8")
        extract = parse_specialists_from_html(html, doctify_url=args.url)
    else:
        extract = extract_practice_sync(args.url, headless=not args.headed)

    result = extract.to_dict()
    sync_result = None
    if args.upsert or args.dry_run:
        dry = args.dry_run or not supabase_configured()
        if args.upsert and dry and not args.dry_run:
            logging.getLogger(__name__).warning(
                "No Supabase credentials — running upsert as dry-run"
            )
        sync_result = sync_doctify_extract(extract, dry_run=dry)

    payload = {"extract": result, "sync": sync_result}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload


def _run_owners_scan(args: argparse.Namespace) -> dict:
    from gtm_pipeline.owner_discovery import discover_owners

    return discover_owners(dry_run=args.dry_run, limit=args.limit)


def _run_people_match_cqc(args: argparse.Namespace) -> dict:
    from gtm_pipeline.person_resolve import match_cqc_people_against_practitioners
    from gtm_pipeline.shared.supabase_client import supabase_configured

    dry = args.dry_run or not supabase_configured()
    return match_cqc_people_against_practitioners(
        registered_manager=args.registered_manager,
        nominated_individual=args.nominated_individual,
        min_confidence=args.min_confidence,
        dry_run=dry,
    )


def _run_people_enrich_cqc(args: argparse.Namespace) -> dict:
    from gtm_pipeline.shared.supabase_client import supabase_configured
    from gtm_pipeline.sync.enrich_cqc_people import enrich_cqc_people_from_practitioners

    dry = args.dry_run or not supabase_configured()
    return enrich_cqc_people_from_practitioners(
        limit=args.limit,
        min_confidence=args.min_confidence,
        dry_run=dry,
    )


def _run_sync_scoped_csv(args: argparse.Namespace) -> dict:
    from gtm_pipeline.shared.supabase_client import supabase_configured
    from gtm_pipeline.sync.scoped_csv import sync_scoped_csv

    dry = args.dry_run or not supabase_configured()
    return sync_scoped_csv(
        args.path,
        dry_run=dry,
        limit=args.limit,
        skip_pre_filtered=not args.include_pre_filtered,
    )


def _run_cqc_match(args: argparse.Namespace) -> dict:
    from gtm_pipeline.cqc_directory import match_directory

    hits = match_directory(
        name=args.name,
        postcode=args.postcode,
        address=args.address,
        website=args.website,
        phone=args.phone,
        top_k=args.top,
    )
    return {"candidates": [h.as_dict() for h in hits]}


def _run_cqc_location(args: argparse.Namespace) -> dict:
    from gtm_pipeline.cqc_location import fetch_location, parse_location_html
    from gtm_pipeline.shared.supabase_client import supabase_configured
    from gtm_pipeline.sync.clinic_intelligence import upsert_clinic_intelligence

    if args.html:
        overview = parse_location_html(args.html.read_text(encoding="utf-8"), location_url=args.url)
    else:
        overview = fetch_location(args.url)

    sync_result = None
    if args.upsert or args.dry_run:
        dry = args.dry_run or not supabase_configured()
        payload = {
            "clinic_account_id": args.clinic_account_id,
            "doctify_url": args.doctify_url,
            "clinic_name": overview.name or None,
            "cqc_location_id": overview.location_id,
            "cqc_location_url": overview.location_url,
            "cqc_registered_since": overview.registered_since.isoformat()
            if overview.registered_since
            else None,
            "cqc_specialisms": overview.specialisms,
            "cqc_registered_manager": overview.registered_manager or None,
            "cqc_nominated_individual": overview.nominated_individual or None,
            "cqc_provider_name": overview.provider_name or None,
            "evidence": overview.evidence,
            "provenance": overview.provenance,
        }
        sync_result = upsert_clinic_intelligence(payload, dry_run=dry)

    return {"overview": overview.to_dict(), "sync": sync_result}


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(prog="gtm_pipeline")
    sub = parser.add_subparsers(dest="group", required=True)
    _add_doctify(sub)
    _add_owners(sub)
    _add_people(sub)
    _add_cqc(sub)
    _add_sync(sub)

    args = parser.parse_args(argv)

    try:
        if args.group == "doctify" and args.command == "extract":
            result = _run_doctify_extract(args)
        elif args.group == "owners" and args.command == "scan":
            result = _run_owners_scan(args)
        elif args.group == "people" and args.command == "match-cqc":
            result = _run_people_match_cqc(args)
        elif args.group == "people" and args.command == "enrich-cqc":
            result = _run_people_enrich_cqc(args)
        elif args.group == "cqc" and args.command == "match":
            result = _run_cqc_match(args)
        elif args.group == "cqc" and args.command == "location":
            result = _run_cqc_location(args)
        elif args.group == "sync" and args.command == "scoped-csv":
            result = _run_sync_scoped_csv(args)
        else:
            parser.error(f"Unknown command: {args.group} {getattr(args, 'command', '')}")
            return
    except Exception as exc:
        logging.getLogger(__name__).exception("Command failed")
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    _json_print(result)


if __name__ == "__main__":
    main()
