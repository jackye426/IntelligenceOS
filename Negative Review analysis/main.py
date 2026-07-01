"""
Harley Street Clinic — Negative Review Analyser
Usage: python main.py [options]

Options:
  --input FILE        Path to clinics CSV (default: auto-detect)
  --limit N           Process only first N clinics
  --max-reviews N     Max negative reviews to collect per clinic (default: 100)
  --headless          Run browser in headless mode
  --refresh           Ignore all caches; re-scrape and re-analyse
  --scrape-only       Stop after scraping (skip analysis and report)
  --analyze-only      Skip scraping; run analysis on already-cached data
  --report-only       Skip scraping and analysis; regenerate report from cache
  --output FILE       Path for the output HTML report
"""

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Ensure stdout is line-buffered so progress prints appear immediately
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, line_buffering=True)

# ── Default CSV location (the user's sales pipeline file) ─────────────────
DEFAULT_CSV = Path(r"C:\Users\yulon\Desktop\Current Projects\Clinic sales agent\output\clinic_sales_results.csv")
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)


def parse_clinics(input_path: Path) -> list[dict]:
    """Read clinic list from a CSV (sales export) or a JSON array."""
    if input_path.suffix.lower() == ".json":
        data = json.loads(input_path.read_text(encoding="utf-8"))
        return [{"name": c["name"], "address": c.get("address", "")} for c in data]

    clinics = []
    with open(input_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("clinic_name") or "").strip()
            location = (row.get("location") or "").strip()
            # Location format: "X.XX miles | Full Address, City, Country, Postcode"
            address = location.split("|", 1)[-1].strip() if "|" in location else location
            if name:
                clinics.append({"name": name, "address": address})
    return clinics


def load_analyses(clinics: list[dict]) -> list[dict]:
    """Load cached analysis JSON files for the given clinics."""
    from slugify import slugify
    analyses = []
    for clinic in clinics:
        slug = slugify(clinic["name"])
        f = DATA_DIR / f"{slug}_analysis.json"
        if f.exists():
            analyses.append(json.loads(f.read_text(encoding="utf-8")))
        else:
            analyses.append({
                "clinic": clinic["name"],
                "review_count": 0,
                "categories": [],
                "summary": "",
                "reviews": [],
            })
    return analyses


def load_scrape_results(clinics: list[dict]) -> list[dict]:
    """Load cached scrape JSON files for the given clinics."""
    from slugify import slugify
    results = []
    for clinic in clinics:
        slug = slugify(clinic["name"])
        f = DATA_DIR / f"{slug}.json"
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append(data)
        else:
            results.append({"clinic": clinic["name"], "reviews": [], "total_negative": 0})
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Analyse negative Google Maps reviews for Harley Street clinics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input", default=None, help="Path to clinics CSV file")
    parser.add_argument("--limit", type=int, default=None, help="Max clinics to process")
    parser.add_argument("--max-reviews", type=int, default=100, dest="max_reviews",
                        help="Max negative reviews per clinic (default: 100)")
    parser.add_argument("--headless", action="store_true", help="Run browser headlessly")
    parser.add_argument("--refresh", action="store_true", help="Ignore cache; re-scrape and re-analyse")
    parser.add_argument("--scrape-only", action="store_true", dest="scrape_only")
    parser.add_argument("--analyze-only", action="store_true", dest="analyze_only")
    parser.add_argument("--report-only", action="store_true", dest="report_only")
    parser.add_argument("--output", default=None, help="Output HTML report path")
    args = parser.parse_args()

    # ── Find CSV ──────────────────────────────────────────────────────────
    input_path = Path(args.input) if args.input else DEFAULT_CSV
    if not input_path.exists():
        print(f"ERROR: Input file not found at '{input_path}'")
        print("Specify with --input <path.csv or path.json>")
        sys.exit(1)

    print(f"Loading clinics from: {input_path}")
    clinics = parse_clinics(input_path)
    if args.limit:
        clinics = clinics[: args.limit]
    print(f"  {len(clinics)} clinics loaded")

    # ── Step 1: Scrape ────────────────────────────────────────────────────
    if not args.analyze_only and not args.report_only:
        print(f"\n{'-'*50}")
        print("STEP 1: Scraping Google Maps reviews")
        print(f"{'-'*50}")

        from scraper import scrape_all

        if sys.platform == "win32":
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

        asyncio.run(
            scrape_all(
                clinics,
                max_reviews=args.max_reviews,
                headless=args.headless,
                refresh=args.refresh,
            )
        )

    if args.scrape_only:
        print("\nScraping complete (--scrape-only). Done.")
        return

    # ── Step 2: Analyse ───────────────────────────────────────────────────
    print(f"\n{'-'*50}")
    print("STEP 2: Analysing reviews with Claude")
    print(f"{'-'*50}")

    from analyzer import analyze_all, analyze_cross_clinic

    if not args.report_only:
        scrape_results = load_scrape_results(clinics)
        all_analyses = analyze_all(scrape_results, refresh=args.refresh)

        print("\nRunning cross-clinic analysis...")
        cross = analyze_cross_clinic(all_analyses)
        cross_file = DATA_DIR / "cross_clinic_analysis.json"
        cross_file.write_text(json.dumps(cross, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print("Loading cached analyses…")
        all_analyses = load_analyses(clinics)
        cross_file = DATA_DIR / "cross_clinic_analysis.json"
        cross = json.loads(cross_file.read_text(encoding="utf-8")) if cross_file.exists() else {}

    # Attach raw reviews to analyses for the report table
    scrape_results = load_scrape_results(clinics)
    scrape_by_name = {r["clinic"]: r for r in scrape_results}
    for analysis in all_analyses:
        raw = scrape_by_name.get(analysis.get("clinic", ""), {})
        analysis["reviews"] = raw.get("reviews", [])

    # ── Step 3: Report ────────────────────────────────────────────────────
    print(f"\n{'-'*50}")
    print("STEP 3: Generating HTML report")
    print(f"{'-'*50}")

    from report import generate_report
    comm_file = DATA_DIR / "communication_deep_dive.json"
    comm_deep_dive = None
    if comm_file.exists():
        comm_deep_dive = json.loads(comm_file.read_text(encoding="utf-8"))
        # attach the review count used for the analysis
        if comm_deep_dive and "total_comm_reviews" not in comm_deep_dive:
            comm_deep_dive["total_comm_reviews"] = sum(
                t.get("count", 0) for t in comm_deep_dive.get("sub_themes", [])
            )
    comm_analysis = None
    comm_analysis_file = DATA_DIR / "comm_report_data.json"
    if comm_analysis_file.exists():
        comm_analysis = json.loads(comm_analysis_file.read_text(encoding="utf-8"))

    bottleneck_data = None
    bottleneck_file = DATA_DIR / "bottleneck_data.json"
    if bottleneck_file.exists():
        bottleneck_data = json.loads(bottleneck_file.read_text(encoding="utf-8"))

    inbound_deep_dive = None
    inbound_file = DATA_DIR / "inbound_deep_dive.json"
    if inbound_file.exists():
        inbound_deep_dive = json.loads(inbound_file.read_text(encoding="utf-8"))

    opportunity_data = None
    opp_summary = DATA_DIR / "opportunity_summary.json"
    opp_dives   = DATA_DIR / "opportunity_deepdives.json"
    if opp_summary.exists():
        opportunity_data = json.loads(opp_summary.read_text(encoding="utf-8"))
        if opp_dives.exists():
            opportunity_data["deep_dives"] = json.loads(opp_dives.read_text(encoding="utf-8"))

    report_path = generate_report(all_analyses, cross, args.output,
                                  comm_deep_dive=comm_deep_dive,
                                  comm_analysis=comm_analysis,
                                  bottleneck_data=bottleneck_data,
                                  inbound_deep_dive=inbound_deep_dive,
                                  opportunity_data=opportunity_data)

    print(f"\nDone! Open your report:")
    print(f"  {report_path}")


if __name__ == "__main__":
    main()
