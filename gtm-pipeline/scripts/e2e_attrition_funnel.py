"""Print E2E GTM attrition funnel from scoped CSV + Supabase."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from gtm_pipeline.shared.supabase_client import get_client, supabase_configured

CSV = Path(__file__).resolve().parents[1] / "data" / "full_scope_run.csv"


def _pct(n: int, d: int) -> str:
    if d <= 0:
        return "n/a"
    return f"{100.0 * n / d:.1f}%"


def main() -> None:
    df = pd.read_csv(CSV, dtype=str).fillna("")
    listing = len(df)
    pre_filtered = int((df["status"] == "pre_filtered").sum())
    kept = listing - pre_filtered
    cqc_matched = int(
        ((df["cqc_location_id"] != "") & (df["cqc_location_id"] != "NOT_FOUND")).sum()
    )
    cqc_not = int((df["cqc_location_id"] == "NOT_FOUND").sum())
    has_ni = int((df["cqc_nominated_individual"].str.strip() != "").sum())
    has_rm = int((df["cqc_registered_manager"].str.strip() != "").sum())
    has_cqc_person = int(
        (
            (df["cqc_nominated_individual"].str.strip() != "")
            | (df["cqc_registered_manager"].str.strip() != "")
        ).sum()
    )
    # among kept only
    kept_df = df[df["status"] != "pre_filtered"]
    kept_cqc = int(
        (
            (kept_df["cqc_location_id"] != "")
            & (kept_df["cqc_location_id"] != "NOT_FOUND")
        ).sum()
    )
    kept_person = int(
        (
            (kept_df["cqc_nominated_individual"].str.strip() != "")
            | (kept_df["cqc_registered_manager"].str.strip() != "")
        ).sum()
    )

    sb: dict = {}
    if supabase_configured():
        client = get_client()
        intel = (
            client.table("gtm_clinic_intelligence")
            .select("id", count="exact")
            .limit(1)
            .execute()
        )
        with_cqc = (
            client.table("gtm_clinic_intelligence")
            .select("id", count="exact")
            .not_.is_("cqc_location_id", "null")
            .limit(1)
            .execute()
        )
        people = (
            client.table("gtm_clinic_people").select("id", count="exact").limit(1).execute()
        )
        people_email = (
            client.table("gtm_clinic_people")
            .select("id", count="exact")
            .not_.is_("email", "null")
            .neq("email", "")
            .limit(1)
            .execute()
        )
        high_score = (
            client.table("gtm_clinic_intelligence")
            .select("id", count="exact")
            .gte("founder_score", 40)
            .limit(1)
            .execute()
        )
        unmatched = (
            client.table("gtm_unmatched_owners")
            .select("practitioner_id", count="exact")
            .limit(1)
            .execute()
        )
        sb = {
            "gtm_clinic_intelligence": intel.count,
            "with_cqc_location": with_cqc.count,
            "gtm_clinic_people": people.count,
            "people_with_email": people_email.count,
            "founder_score_gte_40": high_score.count,
            "gtm_unmatched_owners": unmatched.count,
        }

    funnel = [
        {
            "stage": "1_doctify_listing_profiles",
            "count": listing,
            "of_prior": listing,
            "retention": "100%",
            "note": "unique practice profiles from input_urls.csv scope",
        },
        {
            "stage": "2_pass_prefilter",
            "count": kept,
            "of_prior": listing,
            "retention": _pct(kept, listing),
            "attrition": pre_filtered,
            "note": "dropped hospital/NHS/group pre_filtered",
        },
        {
            "stage": "3_cqc_directory_match",
            "count": kept_cqc,
            "of_prior": kept,
            "retention": _pct(kept_cqc, kept),
            "attrition": kept - kept_cqc,
            "note": f"all-rows matched={cqc_matched} not_found={cqc_not}",
        },
        {
            "stage": "4_cqc_has_rm_or_ni",
            "count": kept_person,
            "of_prior": kept_cqc,
            "retention": _pct(kept_person, kept_cqc) if kept_cqc else "n/a",
            "attrition": kept_cqc - kept_person,
            "note": f"NI rows={has_ni} RM rows={has_rm} (all statuses)",
        },
        {
            "stage": "5_synced_gtm_clinic_intelligence",
            "count": sb.get("gtm_clinic_intelligence"),
            "of_prior": kept,
            "retention": _pct(sb.get("gtm_clinic_intelligence") or 0, kept),
            "note": "Supabase upsert (skip pre_filtered)",
        },
        {
            "stage": "6_synced_with_cqc_id",
            "count": sb.get("with_cqc_location"),
            "of_prior": sb.get("gtm_clinic_intelligence"),
            "retention": _pct(
                sb.get("with_cqc_location") or 0, sb.get("gtm_clinic_intelligence") or 0
            ),
            "note": "intelligence rows with cqc_location_id",
        },
        {
            "stage": "7_gtm_clinic_people",
            "count": sb.get("gtm_clinic_people"),
            "of_prior": sb.get("gtm_clinic_intelligence"),
            "retention": "n/a (can be >1 per clinic)",
            "note": "CQC role people (+ any enrichments)",
        },
        {
            "stage": "8_people_with_email",
            "count": sb.get("people_with_email"),
            "of_prior": sb.get("gtm_clinic_people"),
            "retention": _pct(
                sb.get("people_with_email") or 0, sb.get("gtm_clinic_people") or 0
            ),
            "note": "practitioner email match on CQC names",
        },
        {
            "stage": "9_founder_score_gte_40",
            "count": sb.get("founder_score_gte_40"),
            "of_prior": sb.get("gtm_clinic_intelligence"),
            "retention": _pct(
                sb.get("founder_score_gte_40") or 0, sb.get("gtm_clinic_intelligence") or 0
            ),
            "note": "outreach-ready score band",
        },
        {
            "stage": "10_unmatched_owners_queue",
            "count": sb.get("gtm_unmatched_owners"),
            "of_prior": None,
            "retention": "n/a",
            "note": "owner-first bios with no clinic link (keep email)",
        },
    ]

    out = {"csv": str(CSV), "funnel": funnel, "supabase": sb}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
