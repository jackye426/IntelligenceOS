"""Export London physiotherapy records from Supabase to xlsx."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(REPO_ROOT / ".env")

LONDON_POSTCODE_RE = re.compile(
    r"^(E\d|EC\d|N\d|NW\d|SE\d|SW\d|W\d|WC\d|BR\d|CR\d|DA\d|EN\d|"
    r"HA\d|IG\d|KT\d|RM\d|SM\d|TW\d|UB\d|WD\d)",
    re.I,
)

PHYSIO_SPECIALTY_SQL = (
    "specialty.ilike.%physiotherapist%,"
    "specialty.ilike.%physiotherapy%,"
    "specialty.ilike.Chartered Physiotherapist%,"
    "specialty.ilike.Senior Physiotherapist%,"
    "specialty.ilike.Specialist Physiotherapist%,"
    "specialty.ilike.Specialised Physiotherapist%,"
    "specialty.ilike.MSK%Physiotherapist%"
)

SELECT_COLUMNS = (
    "id,name,specialty,email,emails,website,contact_phone,hcpc_number,"
    "sources,profile_urls,email_source,locations"
)


def _clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _json_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return _clean(value)


def is_london_postcode(postcode: str) -> bool:
    normalized = re.sub(r"\s+", "", postcode or "").upper()
    return bool(normalized and LONDON_POSTCODE_RE.match(normalized))


def is_london_address(address: str) -> bool:
    return bool(re.search(r"\bLondon\b", address or "", re.I))


def is_london_location(loc: dict) -> bool:
    return is_london_postcode(_clean(loc.get("postcode"))) or is_london_address(
        _clean(loc.get("address"))
    )


def specialty_mentions_london(specialty: str) -> bool:
    return bool(re.search(r"\bLondon\b", specialty or "", re.I))


def best_contact(record: dict, loc: dict | None, field: str) -> str:
    for source in (record, loc or {}):
        value = _clean(source.get(field))
        if value:
            return value
    return ""


def fetch_physio_records(client) -> list[dict]:
    rows: list[dict] = []
    page_size = 1000
    offset = 0
    while True:
        batch = (
            client.table("integrated_practitioners")
            .select(SELECT_COLUMNS)
            .or_(PHYSIO_SPECIALTY_SQL)
            .order("id")
            .range(offset, offset + page_size - 1)
            .execute()
            .data
            or []
        )
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


def normalize_postcode(postcode: str) -> str:
    return re.sub(r"\s+", "", postcode or "").upper()


def normalize_address(address: str) -> str:
    return re.sub(r"\s+", " ", (address or "").strip().lower())


def location_dedupe_key(loc: dict) -> str:
    postcode = normalize_postcode(_clean(loc.get("postcode")))
    if postcode:
        return f"pc:{postcode}"
    address = normalize_address(_clean(loc.get("address")))
    if address:
        return f"addr:{address}"
    return ""


def location_richness(loc: dict) -> int:
    score = len(_clean(loc.get("address")))
    if _clean(loc.get("website")):
        score += 100
    if _clean(loc.get("email")):
        score += 50
    if _clean(loc.get("phone")):
        score += 25
    return score


def dedupe_locations(locations: list[dict]) -> list[dict]:
    best_by_key: dict[str, dict] = {}
    for loc in locations:
        key = location_dedupe_key(loc)
        if not key:
            continue
        existing = best_by_key.get(key)
        if existing is None or location_richness(loc) > location_richness(existing):
            best_by_key[key] = loc
    return list(best_by_key.values())


def build_rows(records: list[dict]) -> list[dict]:
    out: list[dict] = []
    for record in records:
        locations = record.get("locations") or []
        if not isinstance(locations, list):
            locations = []

        london_locations = dedupe_locations(
            [
                loc
                for loc in locations
                if isinstance(loc, dict) and is_london_location(loc)
            ]
        )

        if london_locations:
            location_sets = london_locations
        elif specialty_mentions_london(_clean(record.get("specialty"))):
            location_sets = [None]
        else:
            continue

        emails = record.get("emails") or []
        all_emails = ", ".join(
            e for e in ([_clean(record.get("email"))] + [_clean(x) for x in emails if x])
            if e
        )
        unique_emails: list[str] = []
        for email in all_emails.split(", "):
            if email and email not in unique_emails:
                unique_emails.append(email)

        for loc in location_sets:
            out.append(
                {
                    "id": _clean(record.get("id")),
                    "name": _clean(record.get("name")),
                    "specialty": _clean(record.get("specialty")),
                    "email": best_contact(record, loc, "email"),
                    "all_emails": ", ".join(unique_emails),
                    "website": best_contact(record, loc, "website"),
                    "phone": best_contact(record, loc, "phone") or best_contact(
                        record, loc, "contact_phone"
                    ),
                    "location_address": _clean((loc or {}).get("address")),
                    "location_postcode": _clean((loc or {}).get("postcode")),
                    "location_source": _clean((loc or {}).get("source")),
                    "hcpc_number": _clean(record.get("hcpc_number")),
                    "sources": _json_text(record.get("sources")),
                    "profile_urls": _json_text(record.get("profile_urls")),
                    "email_source": _clean(record.get("email_source")),
                }
            )
    return out


def build_clinic_rows(location_rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in location_rows:
        grouped.setdefault(row["id"], []).append(row)

    clinics: list[dict] = []
    for clinic_id, rows in grouped.items():
        first = rows[0]
        locations_text = " | ".join(
            f"{r['location_address']} ({r['location_postcode']})".strip(" ()")
            for r in rows
            if r["location_address"] or r["location_postcode"]
        )
        clinics.append(
            {
                "id": clinic_id,
                "name": first["name"],
                "specialty": first["specialty"],
                "email": first["email"],
                "all_emails": first["all_emails"],
                "website": first["website"],
                "phone": first["phone"],
                "london_location_count": len(rows),
                "london_locations": locations_text,
                "hcpc_number": first["hcpc_number"],
                "sources": first["sources"],
                "profile_urls": first["profile_urls"],
                "email_source": first["email_source"],
            }
        )
    return clinics


def main() -> None:
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env.local")

    client = create_client(url, key)
    records = fetch_physio_records(client)
    rows = build_rows(records)
    if not rows:
        raise SystemExit("No London physiotherapy records found.")

    df = pd.DataFrame(rows)
    df = df.sort_values(["name", "location_postcode", "location_address"], na_position="last")
    clinics_df = pd.DataFrame(build_clinic_rows(rows)).sort_values("name", na_position="last")

    output_dir = REPO_ROOT / "output"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "london_physiotherapists.xlsx"

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        clinics_df.to_excel(writer, sheet_name="Clinics", index=False)
        df.to_excel(writer, sheet_name="London Locations", index=False)
        summary = pd.DataFrame(
            [
                {"metric": "Unique clinics/practices", "value": clinics_df["id"].nunique()},
                {"metric": "Total London location rows", "value": len(df)},
                {"metric": "Clinics with email", "value": int((clinics_df["email"] != "").sum())},
                {"metric": "Clinics with website", "value": int((clinics_df["website"] != "").sum())},
                {"metric": "Clinics with phone", "value": int((clinics_df["phone"] != "").sum())},
                {"metric": "Location rows with email", "value": int((df["email"] != "").sum())},
                {"metric": "Location rows with website", "value": int((df["website"] != "").sum())},
                {"metric": "Location rows with phone", "value": int((df["phone"] != "").sum())},
            ]
        )
        summary.to_excel(writer, sheet_name="Summary", index=False)

        for sheet in writer.sheets.values():
            for column in sheet.columns:
                max_len = 0
                col_letter = column[0].column_letter
                for cell in column:
                    if cell.value is not None:
                        max_len = max(max_len, len(str(cell.value)))
                sheet.column_dimensions[col_letter].width = min(max_len + 2, 60)

    print(
        f"Wrote {clinics_df.shape[0]} clinics ({df.shape[0]} London locations) to {output_path}"
    )


if __name__ == "__main__":
    main()
