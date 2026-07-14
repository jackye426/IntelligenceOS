"""Run Clinic sales agent Doctify scope, then CQC directory lookups.

How scope + CQC fit together
----------------------------
1. **Scope (Doctify listings)** — `Clinic sales agent/input_urls.csv`
   specialty/area listing URLs + page counts. Discovery only; produces practice
   profile rows (name, location, website, doctify URL).

2. **CQC matching** — lookups against a *cached* national directory CSV
   (`Clinic sales agent/output/cqc_directory.csv`, refreshed if >7 days old).
   For each Doctify clinic we match by name + postcode/address extracted from
   the Doctify location string, then scrape that location page for Registered
   Manager / Nominated Individual. We do **not** pull “all of CQC” per run;
   we keep one local directory dump and look clinics up in it.

3. **gtm-pipeline** (optional) — per-practice enrichment (`doctify extract`)
   and numeric `cqc match` using the same directory file via
   `CQC_DIRECTORY_PATH`.

Examples
--------
  # Sample: 1 listing page
  python gtm-pipeline/scripts/run_scoped_discovery.py \\
    --start-url 'https://www.doctify.com/uk/find/endometriosis/harley-street/practices#distance=10' \\
    --pages 1

  # Full Harley Street specialty scope from input_urls.csv
  python gtm-pipeline/scripts/run_scoped_discovery.py --full
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLINIC_AGENT = REPO / "Clinic sales agent"
DEFAULT_OUT = REPO / "gtm-pipeline" / "data" / "scoped_doctify_cqc.csv"


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(CLINIC_AGENT), check=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--full", action="store_true", help="Use Clinic sales agent/input_urls.csv")
    p.add_argument("--start-url", default="", help="Single Doctify listing URL (sample mode)")
    p.add_argument("--pages", type=int, default=None, help="Override page count")
    p.add_argument("--output", type=Path, default=DEFAULT_OUT)
    p.add_argument("--listing-delay", type=float, default=2.0)
    p.add_argument("--skip-scrape", action="store_true", help="Only run CQC on existing --output")
    p.add_argument("--skip-cqc", action="store_true", help="Scrape only")
    p.add_argument("--append", action="store_true", help="Skip clinics already in output CSV")
    args = p.parse_args()

    if not args.full and not args.start_url and not args.skip_scrape:
        p.error("Pass --full, --start-url, or --skip-scrape")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    main_py = str(CLINIC_AGENT / "src" / "main.py")

    if not args.skip_scrape:
        cmd = [
            py,
            main_py,
            "--scrape-only",
            "--output",
            str(args.output),
            "--listing-delay",
            str(args.listing_delay),
        ]
        if args.append:
            cmd.append("--append")
        if args.full:
            if args.pages is not None:
                cmd.extend(["--pages", str(args.pages)])
        else:
            cmd.extend(["--start-url", args.start_url, "--pages", str(args.pages or 1)])
        _run(cmd)

    if not args.skip_cqc:
        _run([py, main_py, "--cqc-only", "--output", str(args.output)])

    print(f"Done. Output: {args.output}")


if __name__ == "__main__":
    main()
