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
    doctify = sub.add_parser("doctify", help="Doctify listing + practice extract (gtm only)")
    dsub = doctify.add_subparsers(dest="command", required=True)

    discover = dsub.add_parser(
        "discover",
        help="Listing discovery -> practice URL stubs (no profile scrape)",
    )
    discover.add_argument(
        "--scope",
        type=Path,
        default=config.DOCTIFY_SCOPE_CSV,
        help="CSV with url,pages columns",
    )
    discover.add_argument("--start-url", default="", help="Single listing URL (overrides scope)")
    discover.add_argument("--pages", type=int, default=None, help="Override pages per URL")
    discover.add_argument("--limit", type=int, default=None, help="Max practice stubs")
    discover.add_argument("--listing-delay", type=float, default=2.0)
    discover.add_argument("--out", type=Path, help="Write stubs JSON (or CSV if .csv)")

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

    batch = dsub.add_parser(
        "extract-batch",
        help="Batch practice extract from Supabase URLs or CSV (Playwright)",
    )
    batch.add_argument(
        "--from-supabase",
        action="store_true",
        help="Load doctify_url rows from gtm_clinic_intelligence",
    )
    batch.add_argument("--csv", type=Path, help="CSV with doctify_url column")
    batch.add_argument(
        "--priority",
        action="store_true",
        help="Email-matched / CQC / founder_score>=40 first (with --from-supabase)",
    )
    batch.add_argument("--limit", type=int, default=None)
    batch.add_argument("--upsert", action="store_true")
    batch.add_argument("--dry-run", action="store_true")
    batch.add_argument("--headed", action="store_true")
    batch.add_argument(
        "--cqc",
        action="store_true",
        help="After extract: gtm cqc match + location (when no CQC yet)",
    )
    batch.add_argument(
        "--refresh-cqc",
        action="store_true",
        help="Force CQC rematch/scrape even if CQC fields exist",
    )
    batch.add_argument("--delay", type=float, default=1.0, help="Seconds between extracts")
    batch.add_argument("--out", type=Path, help="Optional JSON summary path")


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
        help="Batch-match CQC people on gtm_clinic_intelligence -> practitioner emails",
    )
    enrich.add_argument("--limit", type=int, default=None)
    enrich.add_argument("--min-confidence", type=float, default=0.82)
    enrich.add_argument("--dry-run", action="store_true")


def _add_sync(sub: argparse._SubParsersAction) -> None:
    sync = sub.add_parser("sync", help="Supabase sync helpers")
    ssub = sync.add_subparsers(dest="command", required=True)
    scoped = ssub.add_parser(
        "scoped-csv",
        help="(Legacy) Upsert OG scoped CSV into gtm_* — prefer doctify extract-batch",
    )
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


def _add_segments(sub: argparse._SubParsersAction) -> None:
    segments = sub.add_parser("segments", help="Outreach cohort refresh / list")
    ssub = segments.add_subparsers(dest="command", required=True)

    refresh = ssub.add_parser("refresh", help="Rebuild cohort membership from SoR")
    refresh.add_argument("--slug", default="", help="One cohort slug (default: all active)")
    refresh.add_argument("--dry-run", action="store_true")

    listing = ssub.add_parser("list", help="List cohort members")
    listing.add_argument("--slug", required=True)
    listing.add_argument(
        "--status",
        default="",
        help="Filter: needs_contact|ready|found_linkedin|candidate|excluded",
    )
    listing.add_argument("--limit", type=int, default=50)

    cohorts = ssub.add_parser("cohorts", help="List cohort definitions")
    cohorts.add_argument("--all", action="store_true", help="Include inactive")


def _add_contacts(sub: argparse._SubParsersAction) -> None:
    contacts = sub.add_parser("contacts", help="Outreach contacts + enrichment")
    csub = contacts.add_subparsers(dest="command", required=True)

    prepare = csub.add_parser(
        "prepare",
        help="CQC rematch-only + people enrich for needs_contact cohort members",
    )
    prepare.add_argument("--cohort", required=True, help="Cohort slug")
    prepare.add_argument("--limit", type=int, default=50)
    prepare.add_argument("--dry-run", action="store_true")
    prepare.add_argument("--skip-cqc", action="store_true")
    prepare.add_argument("--skip-people", action="store_true")
    prepare.add_argument(
        "--force-cqc",
        action="store_true",
        help="Rematch even when cqc_location_id already set",
    )

    refresh = csub.add_parser(
        "refresh-outreach",
        help="Materialize gtm_outreach_contacts (one PIC per clinic; no network)",
    )
    refresh.add_argument("--cohort", default="", help="Optional cohort slug filter")
    refresh.add_argument("--limit", type=int, default=None)
    refresh.add_argument(
        "--all-people",
        action="store_true",
        help="Include clinics without CQC RM/NI names (default: CQC-named only)",
    )
    refresh.add_argument("--dry-run", action="store_true")

    rr = csub.add_parser(
        "rocketreach",
        help="RocketReach enrich for outreach contacts (everyone; durable by default)",
    )
    rr.add_argument("--cohort", default="")
    rr.add_argument("--limit", type=int, default=20)
    rr.add_argument("--delay", type=float, default=1.0)
    rr.add_argument("--dry-run", action="store_true")
    rr.add_argument("--force", action="store_true")
    rr.add_argument("--sync", action="store_true")

    li = csub.add_parser(
        "linkedin-find",
        help="LinkedIn find for outreach contacts missing URL (everyone; no send)",
    )
    li.add_argument("--cohort", default="")
    li.add_argument("--limit", type=int, default=20)
    li.add_argument("--delay", type=float, default=1.5)
    li.add_argument("--dry-run", action="store_true")
    li.add_argument("--force", action="store_true")
    li.add_argument(
        "--sync",
        action="store_true",
        help="Run inline instead of durable job (default: durable when Supabase up)",
    )

    listing = csub.add_parser("list", help="List outreach contacts")
    listing.add_argument("--status", default="", help="ready|needs_enrichment|needs_review|excluded")
    listing.add_argument("--channel", default="", help="email|linkedin|none")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument(
        "--ready-sales",
        action="store_true",
        help="Export-ready handoff rows with clinic_name",
    )

def _add_cqc(sub: argparse._SubParsersAction) -> None:
    cqc = sub.add_parser("cqc", help="CQC directory + location lanes (P0b)")
    csub = cqc.add_subparsers(dest="command", required=True)

    refresh = csub.add_parser(
        "refresh-directory",
        help="Download/refresh official CQC_directory.csv (auto if missing/stale)",
    )
    refresh.add_argument("--force", action="store_true", help="Re-download even if fresh")
    refresh.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Override destination (default: CQC_DIRECTORY_PATH / GTM_DATA_DIR)",
    )

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


def _run_doctify_discover(args: argparse.Namespace) -> dict:
    from gtm_pipeline.doctify.listing import discover_listings_sync

    stubs = discover_listings_sync(
        None if args.start_url else args.scope,
        start_url=args.start_url,
        pages=args.pages,
        listing_delay=args.listing_delay,
        max_total=args.limit,
    )
    rows = [s.as_dict() for s in stubs]
    payload = {"count": len(rows), "stubs": rows}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        if args.out.suffix.lower() == ".csv":
            import csv

            fields = ["clinic_name", "doctify_url", "location", "specialty_tags", "specialist_count"]
            with args.out.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                for row in rows:
                    out = {**row}
                    out["specialty_tags"] = "|".join(out.get("specialty_tags") or [])
                    w.writerow(out)
        else:
            args.out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload


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


def _run_doctify_extract_batch(args: argparse.Namespace) -> dict:
    from gtm_pipeline.doctify.extract_batch import (
        load_urls_from_csv,
        load_urls_from_supabase,
        run_extract_batch,
    )
    from gtm_pipeline.shared.supabase_client import supabase_configured

    if args.from_supabase:
        items = load_urls_from_supabase(priority=args.priority, limit=args.limit)
    elif args.csv:
        items = load_urls_from_csv(args.csv)
        if args.limit is not None:
            items = items[: args.limit]
    else:
        raise SystemExit("extract-batch requires --from-supabase or --csv")

    dry = args.dry_run or (args.upsert and not supabase_configured())
    if args.upsert and dry and not args.dry_run:
        logging.getLogger(__name__).warning(
            "No Supabase credentials — running upsert as dry-run"
        )

    result = run_extract_batch(
        items,
        upsert=args.upsert or args.dry_run,
        dry_run=dry,
        headed=args.headed,
        cqc=args.cqc,
        refresh_cqc=args.refresh_cqc,
        preserve_cqc=not args.refresh_cqc,
        delay_s=args.delay,
    )
    payload = result.as_dict()
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


def _run_cqc_refresh_directory(args: argparse.Namespace) -> dict:
    from gtm_pipeline.cqc_directory.refresh import download_directory

    status = download_directory(args.path, force=args.force)
    return status.as_dict()


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


def _run_segments_refresh(args: argparse.Namespace) -> dict:
    from gtm_pipeline.segments import refresh_all_cohorts, refresh_cohort

    if args.slug:
        return refresh_cohort(args.slug, dry_run=args.dry_run)
    return refresh_all_cohorts(dry_run=args.dry_run)


def _run_segments_list(args: argparse.Namespace) -> dict:
    from gtm_pipeline.segments import list_members

    return list_members(
        args.slug,
        status=args.status or None,
        limit=args.limit,
    )


def _run_segments_cohorts(args: argparse.Namespace) -> dict:
    from gtm_pipeline.segments import list_cohorts

    rows = list_cohorts(active_only=not args.all)
    return {"cohorts": rows, "count": len(rows)}


def _run_contacts_prepare(args: argparse.Namespace) -> dict:
    from gtm_pipeline.contacts import prepare_cohort_contacts

    return prepare_cohort_contacts(
        args.cohort,
        limit=args.limit,
        dry_run=args.dry_run,
        skip_cqc=args.skip_cqc,
        skip_people=args.skip_people,
        force_cqc=args.force_cqc,
    )


def _run_contacts_refresh_outreach(args: argparse.Namespace) -> dict:
    from gtm_pipeline.contacts import refresh_outreach_contacts

    return refresh_outreach_contacts(
        cqc_named_only=not args.all_people,
        cohort=args.cohort or None,
        limit=args.limit,
        dry_run=args.dry_run,
    )


def _run_contacts_rocketreach(args: argparse.Namespace) -> dict:
    from gtm_pipeline.rocketreach import (
        enqueue_rocketreach_durable,
        rocketreach_enrich_contacts,
    )
    from gtm_pipeline.shared.supabase_client import supabase_configured

    cohort = args.cohort or None
    if args.sync or args.dry_run or not supabase_configured():
        return rocketreach_enrich_contacts(
            limit=args.limit,
            cohort=cohort,
            delay_s=args.delay,
            dry_run=args.dry_run,
            force=args.force,
        )
    return enqueue_rocketreach_durable(
        limit=args.limit,
        cohort=cohort,
        delay_s=args.delay,
        dry_run=False,
        force=args.force,
    )


def _run_contacts_linkedin_find(args: argparse.Namespace) -> dict:
    from gtm_pipeline.linkedin.find import linkedin_find_for_contacts
    from gtm_pipeline.linkedin.jobs import enqueue_linkedin_find_durable
    from gtm_pipeline.shared.supabase_client import supabase_configured

    cohort = args.cohort or None
    if args.sync or args.dry_run or not supabase_configured():
        return linkedin_find_for_contacts(
            limit=args.limit,
            cohort=cohort,
            delay_s=args.delay,
            dry_run=args.dry_run,
            force=args.force,
        )
    return enqueue_linkedin_find_durable(
        cohort=cohort,
        limit=args.limit,
        delay_s=args.delay,
        dry_run=False,
        force=args.force,
    )


def _run_contacts_list(args: argparse.Namespace) -> dict:
    from gtm_pipeline.contacts import list_outreach_contacts, list_ready_for_sales

    if args.ready_sales:
        return list_ready_for_sales(limit=args.limit)
    return list_outreach_contacts(
        status=args.status or None,
        preferred_channel=args.channel or None,
        limit=args.limit,
    )


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(prog="gtm_pipeline")
    sub = parser.add_subparsers(dest="group", required=True)
    _add_doctify(sub)
    _add_owners(sub)
    _add_people(sub)
    _add_cqc(sub)
    _add_sync(sub)
    _add_segments(sub)
    _add_contacts(sub)

    args = parser.parse_args(argv)

    try:
        if args.group == "doctify" and args.command == "discover":
            result = _run_doctify_discover(args)
        elif args.group == "doctify" and args.command == "extract":
            result = _run_doctify_extract(args)
        elif args.group == "doctify" and args.command == "extract-batch":
            result = _run_doctify_extract_batch(args)
        elif args.group == "owners" and args.command == "scan":
            result = _run_owners_scan(args)
        elif args.group == "people" and args.command == "match-cqc":
            result = _run_people_match_cqc(args)
        elif args.group == "people" and args.command == "enrich-cqc":
            result = _run_people_enrich_cqc(args)
        elif args.group == "cqc" and args.command == "refresh-directory":
            result = _run_cqc_refresh_directory(args)
        elif args.group == "cqc" and args.command == "match":
            result = _run_cqc_match(args)
        elif args.group == "cqc" and args.command == "location":
            result = _run_cqc_location(args)
        elif args.group == "sync" and args.command == "scoped-csv":
            result = _run_sync_scoped_csv(args)
        elif args.group == "segments" and args.command == "refresh":
            result = _run_segments_refresh(args)
        elif args.group == "segments" and args.command == "list":
            result = _run_segments_list(args)
        elif args.group == "segments" and args.command == "cohorts":
            result = _run_segments_cohorts(args)
        elif args.group == "contacts" and args.command == "prepare":
            result = _run_contacts_prepare(args)
        elif args.group == "contacts" and args.command == "refresh-outreach":
            result = _run_contacts_refresh_outreach(args)
        elif args.group == "contacts" and args.command == "rocketreach":
            result = _run_contacts_rocketreach(args)
        elif args.group == "contacts" and args.command == "linkedin-find":
            result = _run_contacts_linkedin_find(args)
        elif args.group == "contacts" and args.command == "list":
            result = _run_contacts_list(args)
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
