"""Spire COBPS HTTP client with retries and consultant-id resolution."""

from __future__ import annotations

import logging
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from typing import Any

from spire_monitor.config import (
    API_BASE,
    HTTP_RETRIES,
    HTTP_TIMEOUT_S,
    REQUEST_DELAY_S,
)

logger = logging.getLogger(__name__)

_UA = "appointment-monitor/0.1 (+spire-utilization)"


class SpireApiError(Exception):
    """Raised when a Spire API call fails after retries."""


def consultant_id_from_profile_url(profile_url: str) -> str | None:
    """Parse `-cNNNN` from URL → `CNNNN`. Digits alone are invalid for Spire."""
    m = re.search(r"-c([a-z0-9]+)/?(?:#.*)?$", profile_url.strip(), re.I)
    if not m:
        return None
    return "C" + m.group(1).upper()


def resolve_consultant_id(profile_url: str, configured_id: str | None = None) -> str:
    """
    Resolve ConsultantId: configured → slug with leading C → meta tag on profile.
    Raises SpireApiError if unresolved.
    """
    if configured_id:
        cid = configured_id.strip().upper()
        if not cid.startswith("C"):
            cid = "C" + cid
        return cid

    from_slug = consultant_id_from_profile_url(profile_url)
    if from_slug:
        return from_slug

    meta = _consultant_id_from_html(profile_url)
    if meta:
        return meta

    raise SpireApiError(f"Cannot resolve ConsultantId for {profile_url}")


def _consultant_id_from_html(profile_url: str) -> str | None:
    html = _http_get_text(profile_url)
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
    if not m:
        return None
    cid = m.group(1).strip().upper()
    if not cid.startswith("C"):
        cid = "C" + cid
    return cid


def _http_get_bytes(url: str, *, accept: str = "application/json") -> tuple[int, bytes]:
    last_err: Exception | None = None
    for attempt in range(HTTP_RETRIES):
        try:
            if REQUEST_DELAY_S > 0:
                time.sleep(REQUEST_DELAY_S)
            req = urllib.request.Request(
                url,
                headers={"Accept": accept, "User-Agent": _UA},
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            body = e.read() if hasattr(e, "read") else b""
            if e.code in {429, 502, 503, 408} and attempt + 1 < HTTP_RETRIES:
                wait = 2 ** attempt * 2
                logger.warning("HTTP %s for %s — retry in %ss", e.code, url, wait)
                time.sleep(wait)
                last_err = e
                continue
            raise SpireApiError(f"HTTP {e.code} for {url}: {body[:300]!r}") from e
        except Exception as e:
            if attempt + 1 < HTTP_RETRIES:
                wait = 2 ** attempt * 2
                logger.warning("Request error %s — retry in %ss", e, wait)
                time.sleep(wait)
                last_err = e
                continue
            raise SpireApiError(f"Request failed for {url}: {e}") from e
    raise SpireApiError(f"Request failed for {url}: {last_err}")


def _http_get_text(url: str) -> str:
    status, raw = _http_get_bytes(url, accept="text/html,application/json")
    if status == 204:
        return ""
    return raw.decode("utf-8", errors="replace")


def _http_get_json(url: str) -> Any:
    status, raw = _http_get_bytes(url)
    if status == 204 or not raw.strip():
        return []
    import json

    return json.loads(raw.decode("utf-8"))


def get_locations(consultant_id: str) -> list[dict]:
    url = (
        f"{API_BASE}/LocationApi/GetAvailableLocations"
        f"?consultantId={consultant_id}&locationId="
    )
    data = _http_get_json(url)
    if not isinstance(data, list):
        return []
    return data


def get_first_appointments_for_month(
    consultant_id: str,
    location_id: str,
    month: int,
    year: int,
) -> list[dict]:
    url = (
        f"{API_BASE}/AppointmentApi/GetFirstAppointmentsForLocation"
        f"?consultantId={consultant_id}&month={month}&year={year}"
        f"&locationId={location_id}"
    )
    data = _http_get_json(url)
    return data if isinstance(data, list) else []


def get_appointments_for_day(
    consultant_id: str,
    location_id: str,
    day: date,
) -> list[dict]:
    url = (
        f"{API_BASE}/AppointmentApi/GetAppointmentsForLocationAndDate"
        f"?consultantId={consultant_id}"
        f"&day={day.day}&month={day.month}&year={day.year}"
        f"&locationId={location_id}"
    )
    data = _http_get_json(url)
    return data if isinstance(data, list) else []


def month_range(start: date, months: int) -> list[tuple[int, int]]:
    """List of (month, year) covering `months` calendar months from start."""
    out: list[tuple[int, int]] = []
    y, m = start.year, start.month
    for _ in range(months):
        out.append((m, y))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def scrape_consultant_slots(
    consultant_id: str,
    *,
    lookahead_months: int,
    on_day_error: str = "continue",
) -> tuple[list[dict], dict[str, Any]]:
    """
    Full slot inventory for one consultant.
    Returns (slot_dicts, stats) where each slot_dict has:
      location_id, location_name, starts_at (datetime), amount, duration, currency, organisation_unit
    """
    stats: dict[str, Any] = {
        "locations": 0,
        "days": 0,
        "slots": 0,
        "day_errors": 0,
        "partial": False,
    }
    locations = get_locations(consultant_id)
    stats["locations"] = len(locations)
    if not locations:
        return [], stats

    slots: list[dict] = []
    today = date.today()
    seen_days: set[tuple[str, date]] = set()

    for loc in locations:
        loc_id = str(loc.get("LocationId") or "")
        loc_name = str(loc.get("Name") or loc_id)
        if not loc_id:
            continue
        for month, year in month_range(today, lookahead_months):
            try:
                day_stubs = get_first_appointments_for_month(
                    consultant_id, loc_id, month, year
                )
            except SpireApiError as e:
                logger.warning("Month fetch failed %s %s-%02d: %s", loc_id, year, month, e)
                stats["partial"] = True
                continue

            for stub in day_stubs:
                try:
                    dt_str = stub["SAPDateTime"]["DateTime"]
                    day = datetime.fromisoformat(dt_str).date()
                except (KeyError, TypeError, ValueError):
                    continue
                key = (loc_id, day)
                if key in seen_days:
                    continue
                seen_days.add(key)
                try:
                    day_slots = get_appointments_for_day(consultant_id, loc_id, day)
                except SpireApiError as e:
                    stats["day_errors"] += 1
                    stats["partial"] = True
                    logger.warning("Day fetch failed %s %s: %s", loc_id, day, e)
                    if on_day_error == "raise":
                        raise
                    continue
                stats["days"] += 1
                for s in day_slots:
                    try:
                        starts = datetime.fromisoformat(s["SAPDateTime"]["DateTime"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    slots.append(
                        {
                            "location_id": loc_id,
                            "location_name": loc_name,
                            "starts_at": starts,
                            "amount": s.get("Amount"),
                            "duration": s.get("Duration"),
                            "currency": s.get("Currency"),
                            "organisation_unit": s.get("OrganisationUnit"),
                        }
                    )
                    stats["slots"] += 1

    return slots, stats
