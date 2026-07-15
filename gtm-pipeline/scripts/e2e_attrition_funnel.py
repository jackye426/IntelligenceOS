"""E2E GTM attrition funnel — prefer gtm Playwright provenance.

Default: filter ``gtm_clinic_intelligence`` to
``provenance.source=doctify`` / ``extractor=playwright_practice_v1``.

Use ``--all`` for unfiltered Supabase counts (includes OG-seeded rows).
Optional ``--csv`` still reports legacy scoped-CSV stages for comparison.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from gtm_pipeline.shared.supabase_client import get_client, supabase_configured

DEFAULT_CSV = Path(__file__).resolve().parents[1] / "data" / "full_scope_run.csv"


def _pct(n: int, d: int) -> str:
    if d <= 0:
        return "n/a"
    return f"{100.0 * n / d:.1f}%"


def _is_gtm_playwright(prov: Any) -> bool:
    if not isinstance(prov, dict):
        return False
    if (prov.get("extractor") or "") == "playwright_practice_v1":
        return True
    return (prov.get("source") or "") == "doctify"


def _fetch_all_intel(client) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1000
    offset = 0
    while True:
        batch = (
            client.table("gtm_clinic_intelligence")
            .select(
                "id, doctify_url, founder_score, cqc_location_id, "
                "cqc_registered_manager, cqc_nominated_individual, "
                "listed_specialist_count, visible_clinic_size, provenance"
            )
            .range(offset, offset + page - 1)
            .execute()
            .data
            or []
        )
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return rows


def _people_stats(client, intel_ids: set[str] | None) -> dict[str, int]:
    """Count people (and emails) optionally restricted to clinic_intelligence ids."""
    people_n = 0
    email_n = 0
    page = 1000
    offset = 0
    while True:
        batch = (
            client.table("gtm_clinic_people")
            .select("id, clinic_intelligence_id, email")
            .range(offset, offset + page - 1)
            .execute()
            .data
            or []
        )
        for p in batch:
            if intel_ids is not None and p.get("clinic_intelligence_id") not in intel_ids:
                continue
            people_n += 1
            if (p.get("email") or "").strip():
                email_n += 1
        if len(batch) < page:
            break
        offset += page
    return {"people": people_n, "with_email": email_n}


def _csv_funnel(csv_path: Path) -> list[dict[str, Any]]:
    import pandas as pd

    df = pd.read_csv(csv_path, dtype=str).fillna("")
    listing = len(df)
    pre_filtered = int((df["status"] == "pre_filtered").sum())
    kept = listing - pre_filtered
    kept_df = df[df["status"] != "pre_filtered"]
    kept_cqc = int(
        ((kept_df["cqc_location_id"] != "") & (kept_df["cqc_location_id"] != "NOT_FOUND")).sum()
    )
    kept_person = int(
        (
            (kept_df["cqc_nominated_individual"].str.strip() != "")
            | (kept_df["cqc_registered_manager"].str.strip() != "")
        ).sum()
    )
    return [
        {
            "stage": "csv_1_listing",
            "count": listing,
            "retention": "100%",
            "note": "legacy scoped CSV (OG-era comparison only)",
        },
        {
            "stage": "csv_2_pass_prefilter",
            "count": kept,
            "retention": _pct(kept, listing),
            "attrition": pre_filtered,
        },
        {
            "stage": "csv_3_cqc_match",
            "count": kept_cqc,
            "retention": _pct(kept_cqc, kept),
        },
        {
            "stage": "csv_4_cqc_rm_or_ni",
            "count": kept_person,
            "retention": _pct(kept_person, kept_cqc) if kept_cqc else "n/a",
        },
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--all",
        action="store_true",
        help="Do not filter to playwright/doctify provenance",
    )
    ap.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Optional legacy CSV path for comparison stages",
    )
    args = ap.parse_args()

    if not supabase_configured():
        raise SystemExit("Supabase not configured")

    client = get_client()
    all_rows = _fetch_all_intel(client)
    if args.all:
        rows = all_rows
        filter_note = "all gtm_clinic_intelligence rows"
    else:
        rows = [r for r in all_rows if _is_gtm_playwright(r.get("provenance"))]
        filter_note = "provenance.source=doctify OR extractor=playwright_practice_v1"

    ids = {r["id"] for r in rows if r.get("id")}
    with_cqc = sum(1 for r in rows if r.get("cqc_location_id"))
    with_rm_ni = sum(
        1
        for r in rows
        if (r.get("cqc_registered_manager") or "").strip()
        or (r.get("cqc_nominated_individual") or "").strip()
    )
    size_known = sum(
        1
        for r in rows
        if (r.get("visible_clinic_size") or "") not in ("", "unknown", None)
        or (r.get("listed_specialist_count") is not None and r.get("listed_specialist_count") != "")
    )
    high_score = sum(1 for r in rows if int(r.get("founder_score") or 0) >= 40)
    people = _people_stats(client, ids if not args.all else None)

    unmatched = (
        client.table("gtm_unmatched_owners")
        .select("practitioner_id", count="exact")
        .limit(1)
        .execute()
    )

    n = len(rows)
    funnel = [
        {
            "stage": "1_gtm_playwright_clinics",
            "count": n,
            "of_prior": n,
            "retention": "100%",
            "note": filter_note,
            "all_intelligence_rows": len(all_rows),
        },
        {
            "stage": "2_with_cqc_location",
            "count": with_cqc,
            "of_prior": n,
            "retention": _pct(with_cqc, n),
            "attrition": n - with_cqc,
        },
        {
            "stage": "3_cqc_has_rm_or_ni",
            "count": with_rm_ni,
            "of_prior": with_cqc,
            "retention": _pct(with_rm_ni, with_cqc) if with_cqc else "n/a",
            "attrition": with_cqc - with_rm_ni,
        },
        {
            "stage": "4_size_or_specialist_count_known",
            "count": size_known,
            "of_prior": n,
            "retention": _pct(size_known, n),
            "note": "visible_clinic_size not unknown OR listed_specialist_count set",
        },
        {
            "stage": "5_gtm_clinic_people",
            "count": people["people"],
            "of_prior": n,
            "retention": "n/a (can be >1 per clinic)",
        },
        {
            "stage": "6_people_with_email",
            "count": people["with_email"],
            "of_prior": people["people"],
            "retention": _pct(people["with_email"], people["people"]),
        },
        {
            "stage": "7_founder_score_gte_40",
            "count": high_score,
            "of_prior": n,
            "retention": _pct(high_score, n),
        },
        {
            "stage": "8_unmatched_owners_queue",
            "count": unmatched.count,
            "retention": "n/a",
            "note": "global queue (not provenance-filtered)",
        },
    ]

    out: dict[str, Any] = {
        "filter": filter_note,
        "funnel": funnel,
    }
    csv_path = args.csv if args.csv is not None else (
        DEFAULT_CSV if DEFAULT_CSV.exists() and args.all else None
    )
    if args.csv:
        csv_path = args.csv
    if csv_path and Path(csv_path).exists():
        out["legacy_csv"] = str(csv_path)
        out["legacy_csv_funnel"] = _csv_funnel(Path(csv_path))

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
