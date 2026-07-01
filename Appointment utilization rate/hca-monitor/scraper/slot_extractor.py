"""
Extract appointment slots from either an intercepted API response or the rendered
calendar DOM. Always normalises output to a list of SlotRecord dataclasses.

Slot datetimes are stored as UTC. Display date/time strings use Europe/London.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dateutil import parser as dateutil_parser
from playwright.async_api import Page

from scraper.network_interceptor import CandidateEndpoint

logger = logging.getLogger(__name__)

_TZ_LONDON = ZoneInfo("Europe/London")


@dataclass
class SlotRecord:
    consultant_id: int
    consultant_name: str
    profile_url: str
    location_name: str
    appointment_type: str
    funding_route: str
    slot_datetime: datetime   # UTC
    slot_date: str            # YYYY-MM-DD (London time)
    slot_time: str            # HH:MM (London time)
    slot_timezone: str = "Europe/London"
    price: str | None = None
    source_url: str | None = None


def extract_from_api(
    endpoint: CandidateEndpoint,
    consultant_id: int,
    consultant_name: str,
    profile_url: str,
    location_name: str,
    appointment_type: str,
    funding_route: str,
) -> list[SlotRecord]:
    """Parse slot records from an intercepted API response."""
    import json as _json
    data = endpoint.response_json
    if not data:
        logger.debug("API response_json is None for %s", endpoint.url)
        return []

    # Log structure to identify format
    if isinstance(data, dict):
        logger.info("API response dict keys: %s — preview: %s",
                    list(data.keys())[:10], _json.dumps(data)[:400])
    elif isinstance(data, list):
        logger.info("API response list len=%d — first item: %s",
                    len(data), _json.dumps(data[0])[:400] if data else "(empty)")

    slots: list[SlotRecord] = []

    # Handle list-of-slots format: [{startTime: ..., available: true, ...}, ...]
    if isinstance(data, list):
        for item in data:
            slot = _parse_api_slot_item(
                item, consultant_id, consultant_name, profile_url,
                location_name, appointment_type, funding_route, endpoint.url,
            )
            if slot:
                slots.append(slot)

    # Handle wrapped format: {slots: [...], appointments: [...], data: [...]}
    elif isinstance(data, dict):
        for key in ("slots", "appointments", "data", "results", "items", "availableSlots",
                    "Slots", "AppointmentSlots", "availabilities"):
            if key in data and isinstance(data[key], list):
                for item in data[key]:
                    slot = _parse_api_slot_item(
                        item, consultant_id, consultant_name, profile_url,
                        location_name, appointment_type, funding_route, endpoint.url,
                    )
                    if slot:
                        slots.append(slot)
                if slots:
                    break

    logger.info("API extraction: %d slots from %s", len(slots), endpoint.url)
    return slots


def _parse_api_slot_item(
    item: dict,
    consultant_id: int,
    consultant_name: str,
    profile_url: str,
    location_name: str,
    appointment_type: str,
    funding_route: str,
    source_url: str,
) -> SlotRecord | None:
    if not isinstance(item, dict):
        return None

    # Skip explicitly unavailable slots
    for avail_key in ("available", "isAvailable", "is_available", "status"):
        val = item.get(avail_key)
        if val is not None:
            if isinstance(val, bool) and not val:
                return None
            if isinstance(val, str) and val.lower() in ("false", "unavailable", "booked", "blocked"):
                return None

    # Extract datetime — try common field names in order of preference
    raw_dt = None
    for dt_key in ("startTime", "start_time", "start", "dateTime", "date_time",
                   "slotTime", "slot_time", "appointmentTime", "appointment_time", "time"):
        if dt_key in item:
            raw_dt = item[dt_key]
            break

    if not raw_dt:
        return None

    slot_dt_utc = _parse_datetime_to_utc(raw_dt)
    if not slot_dt_utc:
        return None

    # Convert to London display time
    slot_dt_london = slot_dt_utc.astimezone(_TZ_LONDON)
    slot_date = slot_dt_london.strftime("%Y-%m-%d")
    slot_time = slot_dt_london.strftime("%H:%M")

    # Price
    price = None
    for price_key in ("price", "cost", "fee", "amount"):
        if price_key in item:
            price = str(item[price_key])
            break

    return SlotRecord(
        consultant_id=consultant_id,
        consultant_name=consultant_name,
        profile_url=profile_url,
        location_name=location_name,
        appointment_type=appointment_type,
        funding_route=funding_route,
        slot_datetime=slot_dt_utc,
        slot_date=slot_date,
        slot_time=slot_time,
        price=price,
        source_url=source_url,
    )


def _parse_datetime_to_utc(raw: str | int | float) -> datetime | None:
    if isinstance(raw, (int, float)):
        # Unix timestamp (seconds or milliseconds)
        ts = raw / 1000 if raw > 1e10 else raw
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(raw, str):
        try:
            dt = dateutil_parser.parse(raw)
            if dt.tzinfo is None:
                # Assume London time, convert to UTC
                dt = dt.replace(tzinfo=_TZ_LONDON).astimezone(timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt
        except Exception:
            return None
    return None


async def extract_from_dom(
    page: Page,
    consultant_id: int,
    consultant_name: str,
    profile_url: str,
    location_name: str,
    appointment_type: str,
    funding_route: str,
) -> list[SlotRecord]:
    """
    DOM fallback: parse visible time slot elements from the HCA week-calendar page.

    HCA renders a week-view calendar where:
      - Column headers show "Mon\\nJun 1", "Tue\\nJun 2", etc.
      - Slot buttons show only the time ("9:00", "10:40", ...)
    We use a JavaScript evaluation to correlate each slot button with the date
    of the column it visually sits in.
    """
    slots: list[SlotRecord] = []
    source_url = page.url

    # Strategy 1: JavaScript-based calendar extraction using bounding-rect positioning.
    # HCA renders a week-view grid where each day column has a header ("Jun 5") and
    # slot buttons beneath it. We correlate slots with dates by horizontal position.
    try:
        raw = await page.evaluate(r"""() => {
            const timeRe = /^\d{1,2}:\d{2}$/;
            const dateLabelRe = /^[A-Z][a-z]{2} \d{1,2}$/;

            // Collect all leaf text nodes that look like "Jun 5", "Jun 1", etc.
            const dateLabels = [];
            document.querySelectorAll('*').forEach(el => {
                if (el.children.length > 0) return;  // leaf nodes only
                const text = (el.textContent || '').trim();
                if (!dateLabelRe.test(text)) return;
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) return;
                dateLabels.push({text, centerX: rect.left + rect.width / 2});
            });

            if (dateLabels.length === 0) return [];

            // For each slot button, find the date label whose centerX is closest
            const results = [];
            document.querySelectorAll('button').forEach(btn => {
                const text = (btn.textContent || '').trim();
                if (!timeRe.test(text)) return;
                const rect = btn.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) return;
                const btnCenterX = rect.left + rect.width / 2;
                let closest = null, minDist = Infinity;
                for (const lbl of dateLabels) {
                    const d = Math.abs(lbl.centerX - btnCenterX);
                    if (d < minDist) { minDist = d; closest = lbl; }
                }
                if (closest) results.push({time: text, dateLabel: closest.text});
            });
            return results;
        }""")

        if raw:
            logger.info("DOM calendar extraction: %d raw slot entries", len(raw))
            year = datetime.now(_TZ_LONDON).year
            for entry in raw:
                try:
                    dt_str = f"{entry['dateLabel']} {year} {entry['time']}"
                    slot_dt_utc = _parse_datetime_to_utc(dt_str)
                    if not slot_dt_utc:
                        continue
                    slot_dt_london = slot_dt_utc.astimezone(_TZ_LONDON)
                    slots.append(SlotRecord(
                        consultant_id=consultant_id,
                        consultant_name=consultant_name,
                        profile_url=profile_url,
                        location_name=location_name,
                        appointment_type=appointment_type,
                        funding_route=funding_route,
                        slot_datetime=slot_dt_utc,
                        slot_date=slot_dt_london.strftime("%Y-%m-%d"),
                        slot_time=slot_dt_london.strftime("%H:%M"),
                        source_url=source_url,
                    ))
                except Exception as e:
                    logger.debug("DOM slot parse error (%s): %s", entry, e)

    except Exception as e:
        logger.debug("JS-based DOM extraction failed: %s", e)

    # Strategy 2: legacy selector fallbacks
    if not slots:
        slot_selectors = [
            "button.available-slot",
            "[data-slot-time]",
            ".time-slot:not(.disabled):not(.unavailable)",
            ".slot-button:not([disabled])",
            ".appointment-slot",
            "[data-testid='time-slot']",
            ".available-time",
        ]
        for selector in slot_selectors:
            try:
                els = page.locator(selector)
                count = await els.count()
                if count == 0:
                    continue
                logger.info("DOM extraction: found %d elements with selector '%s'", count, selector)
                for i in range(count):
                    el = els.nth(i)
                    slot = await _parse_dom_slot_element(
                        el, consultant_id, consultant_name, profile_url,
                        location_name, appointment_type, funding_route, source_url,
                    )
                    if slot:
                        slots.append(slot)
                if slots:
                    break
            except Exception as e:
                logger.debug("Selector '%s' failed: %s", selector, e)

    if not slots:
        logger.warning("DOM extraction found no slots. Page URL: %s", source_url)

    return slots


async def _parse_dom_slot_element(
    el,
    consultant_id: int,
    consultant_name: str,
    profile_url: str,
    location_name: str,
    appointment_type: str,
    funding_route: str,
    source_url: str,
) -> SlotRecord | None:
    try:
        # Try data attributes first
        raw_dt = await el.get_attribute("data-slot-time") or \
                 await el.get_attribute("data-datetime") or \
                 await el.get_attribute("data-time") or \
                 await el.get_attribute("data-start")

        if not raw_dt:
            # Fall back to visible text
            text = (await el.text_content() or "").strip()
            if not text:
                return None
            raw_dt = text

        slot_dt_utc = _parse_datetime_to_utc(raw_dt)
        if not slot_dt_utc:
            # Try combining with date from a parent container
            slot_dt_utc = await _infer_datetime_from_context(el, raw_dt)
        if not slot_dt_utc:
            return None

        slot_dt_london = slot_dt_utc.astimezone(_TZ_LONDON)
        slot_date = slot_dt_london.strftime("%Y-%m-%d")
        slot_time = slot_dt_london.strftime("%H:%M")

        price_attr = await el.get_attribute("data-price")

        return SlotRecord(
            consultant_id=consultant_id,
            consultant_name=consultant_name,
            profile_url=profile_url,
            location_name=location_name,
            appointment_type=appointment_type,
            funding_route=funding_route,
            slot_datetime=slot_dt_utc,
            slot_date=slot_date,
            slot_time=slot_time,
            price=price_attr,
            source_url=source_url,
        )
    except Exception as e:
        logger.debug("DOM slot parse error: %s", e)
        return None


async def _infer_datetime_from_context(el, time_text: str) -> datetime | None:
    """Try to find the date from a parent/ancestor element to combine with time_text."""
    try:
        # Walk up to find a date label (e.g. "Thursday 15 May 2025")
        date_el = el.locator("xpath=ancestor::*[contains(@class,'day') or contains(@class,'date')]").first
        if await date_el.count() > 0:
            date_text = (await date_el.get_attribute("data-date") or
                         await date_el.get_attribute("data-day") or
                         await date_el.text_content() or "").strip()
            if date_text:
                combined = f"{date_text} {time_text}"
                return _parse_datetime_to_utc(combined)
    except Exception:
        pass
    return None
