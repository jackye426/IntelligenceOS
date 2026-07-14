"""Prelim: re-match NOT_FOUND clinics by name-only and website-only."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "Clinic sales agent" / "src"))
sys.path.insert(0, str(REPO / "gtm-pipeline" / "src"))

from cqc_lookup import (  # noqa: E402
    _core_words,
    _get_dir,
    _strip_branch,
    _word_overlap,
)
from gtm_pipeline.shared.match_confidence import _website_score  # noqa: E402
from gtm_pipeline.shared.name import normalise_name  # noqa: E402

CSV = REPO / "gtm-pipeline" / "data" / "full_scope_run.csv"
OUT = REPO / "gtm-pipeline" / "data" / "cqc_rematch_prelim.csv"


def _domain(url: str) -> str:
    if not url or not str(url).strip():
        return ""
    u = str(url).strip()
    if not u.startswith("http"):
        u = "https://" + u
    try:
        host = urlparse(u).netloc.lower()
    except Exception:
        return ""
    host = host.removeprefix("www.")
    # Drop booking/query junk hosts
    if not host or host in {"doctify.com", "hcahealthcare.co.uk"}:
        return ""
    return host


def name_only_match(clinic_name: str, df: pd.DataFrame) -> dict | None:
    base = _strip_branch(clinic_name)
    base_lower = base.lower().strip()
    # exact
    for candidate in (clinic_name, base):
        exact = df[df["_name_lower"] == candidate.lower().strip()]
        if not exact.empty:
            return exact.iloc[0].to_dict()
    # contains
    if len(base_lower) >= 4:
        contains = df[df["_name_lower"].str.contains(re.escape(base_lower), regex=True, na=False)]
        if not contains.empty:
            return contains.iloc[contains["Name"].str.len().argmin()].to_dict()
    # word overlap whole directory (threshold 0.75 like strategy 3)
    scores = df["_name_lower"].apply(lambda n: _word_overlap(base, n))
    best = float(scores.max()) if len(scores) else 0.0
    if best >= 0.75:
        top = df[scores == best]
        wa = _core_words(base)
        best_row = top.iloc[top["_name_lower"].apply(lambda n: len(wa & _core_words(n))).argmax()]
        return best_row.to_dict()
    # softer 0.6 for prelim only
    if best >= 0.6:
        top = df[scores == best]
        wa = _core_words(base)
        best_row = top.iloc[top["_name_lower"].apply(lambda n: len(wa & _core_words(n))).argmax()]
        row = best_row.to_dict()
        row["_soft"] = True
        row["_overlap"] = best
        return row
    return None


def website_only_match(website_url: str, df: pd.DataFrame, by_domain: dict[str, list[dict]]) -> dict | None:
    dom = _domain(website_url)
    if not dom:
        return None
    # exact domain
    hits = by_domain.get(dom) or []
    if hits:
        return hits[0]
    # parent domain (e.g. london-gynaecology.com)
    parts = dom.split(".")
    if len(parts) > 2:
        parent = ".".join(parts[-2:])
        hits = by_domain.get(parent) or []
        if hits:
            return hits[0]
    # score fallback against small set is expensive; skip for prelim
    return None


def main() -> None:
    src = pd.read_csv(CSV, dtype=str).fillna("")
    nf = src[src["cqc_location_id"] == "NOT_FOUND"].copy()
    print(f"NOT_FOUND to rematch: {len(nf)}")

    cqc = _get_dir()
    # website index
    web_col = "Service's website (if available)"
    by_domain: dict[str, list[dict]] = {}
    with_web = 0
    for _, row in cqc.iterrows():
        d = _domain(row.get(web_col, ""))
        if not d:
            continue
        with_web += 1
        by_domain.setdefault(d, []).append(row.to_dict())
    print(f"CQC rows with website domain: {with_web} unique domains={len(by_domain)}")

    name_hits_strict = 0
    name_hits_soft = 0
    web_hits = 0
    both = 0
    rows = []

    for _, r in nf.iterrows():
        name_hit = name_only_match(r["clinic_name"], cqc)
        soft = bool(name_hit and name_hit.get("_soft"))
        if name_hit and not soft:
            name_hits_strict += 1
        elif soft:
            name_hits_soft += 1

        web_hit = website_only_match(r.get("website_url", ""), cqc, by_domain)
        if web_hit:
            web_hits += 1
        if name_hit and web_hit:
            both += 1

        rows.append(
            {
                "clinic_name": r["clinic_name"],
                "location": r["location"],
                "website_url": r["website_url"],
                "name_match": (name_hit or {}).get("Name", ""),
                "name_postcode": (name_hit or {}).get("Postcode", ""),
                "name_soft": soft,
                "name_overlap": (name_hit or {}).get("_overlap", ""),
                "name_location_id": (name_hit or {}).get("CQC Location ID (for office use only)", ""),
                "web_match": (web_hit or {}).get("Name", ""),
                "web_postcode": (web_hit or {}).get("Postcode", ""),
                "web_location_id": (web_hit or {}).get("CQC Location ID (for office use only)", ""),
                "agree": bool(
                    name_hit
                    and web_hit
                    and (name_hit.get("CQC Location ID (for office use only)")
                    == web_hit.get("CQC Location ID (for office use only)"))
                ),
            }
        )

    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)

    either_strict = out[(out["name_match"] != "") & (out["name_soft"] == False)]  # noqa: E712
    either_soft = out[out["name_soft"] == True]  # noqa: E712
    web_only = out[(out["web_match"] != "") & (out["name_match"] == "")]
    name_only = out[(out["name_match"] != "") & (out["web_match"] == "")]
    agree = out[out["agree"] == True]  # noqa: E712

    print("--- prelim results on NOT_FOUND ---")
    print(f"name-only strict (>=0.75 / exact/contains): {name_hits_strict} / {len(nf)} ({name_hits_strict/len(nf):.1%})")
    print(f"name-only soft  (>=0.60 overlap):           {name_hits_soft} / {len(nf)} ({name_hits_soft/len(nf):.1%})")
    print(f"website-only exact domain:                  {web_hits} / {len(nf)} ({web_hits/len(nf):.1%})")
    print(f"both name+web hit (any):                    {both}")
    print(f"name+web same location_id:                  {len(agree)}")
    print(f"web hit but no name hit:                    {len(web_only)}")
    print(f"name hit but no web hit:                    {len(name_only)}")
    print(f"wrote {OUT}")

    print("\nSample name-only recoveries (strict):")
    for _, r in either_strict.head(12).iterrows():
        print(f"  {r.clinic_name!r} -> {r.name_match!r} ({r.name_postcode})")

    print("\nSample website-only recoveries:")
    for _, r in out[out["web_match"] != ""].head(12).iterrows():
        print(f"  {r.clinic_name!r} web={r.website_url!r} -> {r.web_match!r}")

    # spotlight Luna
    luna = out[out["clinic_name"].str.contains("Luna", case=False, na=False)]
    print("\nLuna rows:")
    print(luna[["clinic_name", "name_match", "name_postcode", "web_match"]].to_string(index=False))


if __name__ == "__main__":
    main()
