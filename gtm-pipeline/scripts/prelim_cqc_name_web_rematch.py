"""Prelim: re-match NOT_FOUND clinics via gtm cqc_directory (no OG cqc_lookup)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "gtm-pipeline" / "src"))

from gtm_pipeline.cqc_directory import match_directory  # noqa: E402

CSV = REPO / "gtm-pipeline" / "data" / "full_scope_run.csv"
OUT = REPO / "gtm-pipeline" / "data" / "cqc_rematch_prelim.csv"


def main() -> None:
    if not CSV.exists():
        raise SystemExit(f"Missing {CSV}")

    df = pd.read_csv(CSV, dtype=str).fillna("")
    nf = df[df["cqc_location_id"].isin(["", "NOT_FOUND"])].copy()
    rows = []
    for _, row in nf.iterrows():
        name = (row.get("clinic_name") or "").strip()
        if not name:
            continue
        hits = match_directory(
            name=name,
            postcode=row.get("postcode") or row.get("location") or "",
            address=row.get("address") or row.get("location") or "",
            website=row.get("website_url") or row.get("website") or "",
            top_k=1,
        )
        best = hits[0] if hits else None
        rows.append(
            {
                "clinic_name": name,
                "doctify_url": row.get("doctify_profile_url") or row.get("doctify_url") or "",
                "prev_cqc": row.get("cqc_location_id") or "",
                "matched": bool(best and best.confidence >= 0.8),
                "confidence": best.confidence if best else None,
                "cqc_location_id": best.location_id if best else "",
                "cqc_location_url": best.location_url if best else "",
                "reasons": "|".join(best.reasons) if best else "",
            }
        )

    out = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    matched = int(out["matched"].sum()) if len(out) else 0
    print(f"NOT_FOUND={len(nf)} rematched>={0.8}: {matched} → {OUT}")


if __name__ == "__main__":
    main()
