#!/usr/bin/env python3
"""Verify Spire Cardiff roster profiles expose COBPS booking APIs."""

from __future__ import annotations

import json
import re
import urllib.request

API = "https://appointments.spirehealthcare.com/Umbraco/Api"

PROFILES = [
    (
        "Simon Phillips",
        "https://www.spirehealthcare.com/consultant-profiles/mr-simon-phillips-c4069414/",
        "C4069414",
    ),
    (
        "Julie Cornish",
        "https://www.spirehealthcare.com/spire-cardiff-hospital/consultants/julie-cornish-c6031568/",
        "C6031568",
    ),
    (
        "Faris Soliman",
        "https://www.spirehealthcare.com/spire-cardiff-hospital/consultants/mr-faris-soliman-c7082057/",
        "C7082057",
    ),
]


def get_json(url: str):
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        if r.status == 204:
            return []
        return json.loads(r.read().decode())


def get_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def main() -> None:
    for name, url, expected in PROFILES:
        print("===", name, "===")
        print("url", url)
        try:
            html = get_html(url)
            print("profile_http", "ok", "chars", len(html))
        except Exception as e:
            print("PROFILE FETCH FAIL", e)
            # Still try API with expected id
            html = ""
            print("falling back to expected id", expected)

        meta = None
        m = re.search(
            r'name=["\']ConsultantId["\'][^>]*content=["\']([^"\']+)',
            html,
            re.I,
        )
        if not m:
            m = re.search(
                r'content=["\']([^"\']+)["\'][^>]*name=["\']ConsultantId["\']',
                html,
                re.I,
            )
        if m:
            meta = m.group(1)

        slug = re.search(r"-c([a-z0-9]+)/?$", url, re.I)
        slug_id = slug.group(1).upper() if slug else None
        cobps = any(
            s in html
            for s in ("cobpsBaseUrl", "cobpsCalendar", "AppointmentCalendar")
        )
        selfpay = re.search(
            r'IsSelfPayEnabledForConsultant[^>]*value=["\']([^"\']+)', html
        )
        pmi = re.search(
            r'IsPmiEnabledForConsultant[^>]*value=["\']([^"\']+)', html
        )
        print("meta ConsultantId", meta)
        print("slug id", slug_id, "expected", expected)
        print("cobps widget present", cobps)
        print(
            "selfpay",
            selfpay.group(1) if selfpay else None,
            "pmi",
            pmi.group(1) if pmi else None,
        )

        cid = meta or slug_id or expected
        try:
            locs = get_json(
                f"{API}/LocationApi/GetAvailableLocations?consultantId={cid}&locationId="
            )
        except Exception as e:
            print("locations FAIL", e)
            print()
            continue

        print("locations", len(locs) if isinstance(locs, list) else locs)
        for loc in (locs or [])[:5]:
            print(
                " ",
                loc.get("Name"),
                loc.get("LocationId"),
                "£",
                loc.get("ConsultantPrice"),
            )
            days = get_json(
                f"{API}/AppointmentApi/GetFirstAppointmentsForLocation"
                f"?consultantId={cid}&month=9&year=2026&locationId={loc['LocationId']}"
            )
            print(
                "  Sep2026 days with availability",
                len(days) if isinstance(days, list) else days,
            )
            if isinstance(days, list) and days:
                d0 = days[0]["SAPDateTime"]["DateTime"]
                y, mth, day = int(d0[0:4]), int(d0[5:7]), int(d0[8:10])
                slots = get_json(
                    f"{API}/AppointmentApi/GetAppointmentsForLocationAndDate"
                    f"?consultantId={cid}&day={day}&month={mth}&year={y}&locationId={loc['LocationId']}"
                )
                print("  sample day", d0[:10], "slots", len(slots) if isinstance(slots, list) else slots)
        print()


if __name__ == "__main__":
    main()
