"""GTM scoped discovery — listing + extract + CQC via gtm-pipeline only.

Never invokes Clinic sales agent (OG) scraper or ``cqc_lookup.py``.

Flow
----
1. **Listing** — ``gtm_pipeline.doctify.listing`` against
   ``gtm-pipeline/config/doctify_scope.csv`` (copy of Clinic sales ``input_urls.csv``
   scope URLs only).
2. **Extract** — Playwright practice extract (``extract_practice_sync``) + upsert.
3. **CQC** — ``gtm_pipeline.cqc_directory`` match + ``cqc_location`` scrape.

Examples
--------
  # Sample: 1 listing page → extract + CQC
  python gtm-pipeline/scripts/run_scoped_discovery.py \\
    --start-url 'https://www.doctify.com/uk/find/endometriosis/harley-street/practices#distance=10' \\
    --pages 1 --limit 5 --upsert

  # Full Harley Street specialty scope
  python gtm-pipeline/scripts/run_scoped_discovery.py --full --upsert --cqc
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GTM = REPO / "gtm-pipeline"
DEFAULT_SCOPE = GTM / "config" / "doctify_scope.csv"
DEFAULT_OUT = GTM / "data" / "scoped_listing_stubs.csv"
_OG_ROOT = REPO / "Clinic sales agent"


def _guard_no_og(paths: list[Path | str]) -> None:
    """Fail hard if anything under Clinic sales agent/ is invoked."""
    for p in paths:
        resolved = Path(p).resolve()
        try:
            resolved.relative_to(_OG_ROOT.resolve())
        except ValueError:
            continue
        raise SystemExit(
            f"GTM runners must not invoke Clinic sales agent paths. Refused: {resolved}\n"
            "Use gtm-pipeline doctify discover / extract-batch / cqc instead."
        )


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--full",
        action="store_true",
        help=f"Use scope CSV ({DEFAULT_SCOPE.name})",
    )
    p.add_argument("--scope", type=Path, default=DEFAULT_SCOPE, help="Doctify listing scope CSV")
    p.add_argument("--start-url", default="", help="Single Doctify listing URL (sample mode)")
    p.add_argument("--pages", type=int, default=None, help="Override page count per listing URL")
    p.add_argument("--output", type=Path, default=DEFAULT_OUT, help="Listing stubs CSV")
    p.add_argument("--listing-delay", type=float, default=2.0)
    p.add_argument("--limit", type=int, default=None, help="Max practice URLs after listing")
    p.add_argument("--skip-listing", action="store_true", help="Use existing --output stubs CSV")
    p.add_argument("--skip-extract", action="store_true", help="Listing only (write stubs CSV)")
    p.add_argument("--upsert", action="store_true", help="Upsert extracts to Supabase")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--cqc", action="store_true", help="Run gtm CQC match+location after extract")
    p.add_argument("--refresh-cqc", action="store_true", help="Force CQC rematch even if present")
    p.add_argument("--extract-delay", type=float, default=1.0)
    p.add_argument("--headed", action="store_true")
    args = p.parse_args()

    _guard_no_og(
        [
            args.scope if args.scope.exists() else DEFAULT_SCOPE,
            # Explicit refuse if user points output into OG tree
            args.output,
        ]
    )
    # Belt-and-braces: never allow OG main/scraper on argv
    joined = " ".join(sys.argv).lower()
    for bad in ("clinic sales agent", "doctify_scraper", "cqc_lookup", "main.py --scrape"):
        if bad in joined:
            raise SystemExit(f"Refused: GTM scoped discovery must not call OG ({bad!r})")

    if not args.full and not args.start_url and not args.skip_listing:
        p.error("Pass --full, --start-url, or --skip-listing")

    # Ensure scope is under gtm-pipeline (copy), not requiring OG runtime
    if args.full and not args.scope.exists():
        raise SystemExit(
            f"Scope CSV missing: {args.scope}\n"
            "Expected gtm-pipeline/config/doctify_scope.csv (listing URLs only)."
        )

    sys.path.insert(0, str(GTM / "src"))

    stubs: list[dict] = []
    if not args.skip_listing:
        from gtm_pipeline.doctify.listing import discover_listings_sync

        listing_stubs = discover_listings_sync(
            None if args.start_url else args.scope,
            start_url=args.start_url,
            pages=args.pages,
            listing_delay=args.listing_delay,
            max_total=args.limit,
        )
        stubs = [s.as_dict() for s in listing_stubs]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "clinic_name",
            "doctify_url",
            "location",
            "specialty_tags",
            "specialist_count",
        ]
        with args.output.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for row in stubs:
                out = {**row}
                out["specialty_tags"] = "|".join(out.get("specialty_tags") or [])
                w.writerow(out)
        print(f"Listing stubs: {len(stubs)} → {args.output}", flush=True)
    else:
        if not args.output.exists():
            raise SystemExit(f"--skip-listing but missing {args.output}")
        with args.output.open(encoding="utf-8") as f:
            stubs = list(csv.DictReader(f))
        print(f"Loaded {len(stubs)} stubs from {args.output}", flush=True)

    if args.skip_extract:
        print(json.dumps({"listing_count": len(stubs), "output": str(args.output)}, indent=2))
        return

    from gtm_pipeline.doctify.extract_batch import BatchItem, run_extract_batch

    items = [
        BatchItem(
            doctify_url=(r.get("doctify_url") or "").strip().rstrip("/"),
            clinic_name=(r.get("clinic_name") or "").strip(),
        )
        for r in stubs
        if (r.get("doctify_url") or "").strip()
    ]
    if args.limit is not None:
        items = items[: args.limit]

    result = run_extract_batch(
        items,
        upsert=args.upsert,
        dry_run=args.dry_run,
        headed=args.headed,
        cqc=args.cqc,
        refresh_cqc=args.refresh_cqc,
        preserve_cqc=not args.refresh_cqc,
        delay_s=args.extract_delay,
    )
    print(json.dumps(result.as_dict(), indent=2, default=str))


if __name__ == "__main__":
    main()
