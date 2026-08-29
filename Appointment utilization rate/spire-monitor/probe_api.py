#!/usr/bin/env python3
"""Probe Spire COBPS appointment APIs for one consultant (no browser)."""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import datetime

API_BASE = "https://appointments.spirehealthcare.com/Umbraco/Api"


def _get(url: str) -> list | dict:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "spire-monitor-probe/0.1"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status == 204:
            return []
        return json.loads(resp.read().decode())


def consultant_id_from_slug(slug: str) -> str:
    m = re.search(r"-c([a-z0-9]+)$", slug, re.I)
    if not m:
        raise ValueError(f"Cannot parse consultant id from slug: {slug}")
    return m.group(1).upper()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--consultant-id",
        default="C4069414",
        help="Spire ConsultantId (meta tag on profile page)",
    )
    parser.add_argument("--months", type=int, default=3, help="Months ahead to scan")
    args = parser.parse_args()

    cid = args.consultant_id
    print(f"ConsultantId: {cid}")

    locations = _get(f"{API_BASE}/LocationApi/GetAvailableLocations?consultantId={cid}&locationId=")
    if not locations:
        print("No online-booking locations returned.")
        return
    print(f"Locations: {len(locations)}")
    for loc in locations:
        print(f"  - {loc['Name']} ({loc['LocationId']}) £{loc.get('ConsultantPrice')}")

    now = datetime.now()
    total_slots = 0
    for loc in locations:
        loc_id = loc["LocationId"]
        print(f"\n=== {loc['Name']} ===")
        for offset in range(args.months):
            month = ((now.month - 1 + offset) % 12) + 1
            year = now.year + (now.month - 1 + offset) // 12
            days = _get(
                f"{API_BASE}/AppointmentApi/GetFirstAppointmentsForLocation"
                f"?consultantId={cid}&month={month}&year={year}&locationId={loc_id}"
            )
            print(f"  {year}-{month:02d}: {len(days)} day(s) with availability")
            for day_stub in days[:5]:
                dt = day_stub["SAPDateTime"]["DateTime"]
                d = datetime.fromisoformat(dt)
                day_slots = _get(
                    f"{API_BASE}/AppointmentApi/GetAppointmentsForLocationAndDate"
                    f"?consultantId={cid}&day={d.day}&month={d.month}&year={d.year}&locationId={loc_id}"
                )
                total_slots += len(day_slots)
                times = ", ".join(s["SAPDateTime"]["DateTime"][11:16] for s in day_slots)
                print(f"    {d.date()}: {len(day_slots)} slot(s) [{times}]")

    print(f"\nSampled slot count (first 5 days/month only): {total_slots}")


if __name__ == "__main__":
    main()
