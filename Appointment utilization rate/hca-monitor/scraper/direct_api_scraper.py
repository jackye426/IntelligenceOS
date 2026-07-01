"""
Direct API scraper — bypasses the full booking-flow UI navigation.

For consultants whose (consultantGUID, locationGUID) pairs are already stored
in the booking_guids table:

  1. Visit the T&C page once (domcontentloaded, no clicking) to acquire the
     Incapsula session cookie the API requires.
  2. Call GetLDBConsultantSlots directly for every (location × appt_type × week)
     combination — no Playwright slow_mo, no location card navigation, no calendar
     pagination.

Consultants with no stored GUIDs still go through booking_navigator.py (full browser
flow). Their GUIDs are stored in source_url on AppointmentSlot rows and picked up by
guid_store.populate_from_slots() at the next startup.
"""

import asyncio
import json as _json
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from playwright.async_api import BrowserContext

from config.settings import settings
from db.models import BookingGuid
from scraper.network_interceptor import CandidateEndpoint
from scraper.slot_extractor import SlotRecord, extract_from_api

logger = logging.getLogger(__name__)

_BASE_API = "https://www.hcahealthcare.co.uk/api/C2/GetLDBConsultantSlots"
_TC_BASE  = "https://www.hcahealthcare.co.uk/finder/step-terms-and-conditions"


async def scrape_consultant_direct(
    context: BrowserContext,
    consultant_id: int,
    consultant_name: str,
    profile_url: str,
    guids: list[BookingGuid],
) -> list[SlotRecord]:
    """
    Scrape all slots for a consultant using stored GUIDs and direct API calls.
    One lightweight page load per consultant; no per-location UI navigation.
    """
    slug = profile_url.rstrip("/").split("/")[-1]
    tc_url = f"{_TC_BASE}?slug={slug}"

    # One page load to acquire the session cookie the API requires
    page = await context.new_page()
    try:
        logger.info("Direct API: acquiring session for '%s' via %s", consultant_name, tc_url)
        await page.goto(tc_url, wait_until="domcontentloaded", timeout=15000)
    except Exception as e:
        logger.warning("T&C page load warning for '%s': %s", consultant_name, e)
    finally:
        await page.close()

    # Build the week schedule (Monday-aligned, covering full lookahead window)
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=settings.max_lookahead_days)
    week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start -= timedelta(days=week_start.weekday())

    weeks: list[tuple[str, str]] = []
    for _ in range(settings.max_lookahead_days // 7 + 2):
        if week_start > cutoff:
            break
        weeks.append((
            week_start.strftime("%Y-%m-%d"),
            (week_start + timedelta(days=6)).strftime("%Y-%m-%d"),
        ))
        week_start += timedelta(days=7)

    all_slots: list[SlotRecord] = []

    for guid_row in guids:
        for is_follow_on, appt_type in (("false", "initial"), ("true", "follow-up")):
            location_slots = await _fetch_all_weeks(
                context=context,
                consultant_id=consultant_id,
                consultant_name=consultant_name,
                profile_url=profile_url,
                location_name=guid_row.location_name,
                funding_route=guid_row.funding_route,
                appointment_type=appt_type,
                consultant_guid=guid_row.consultant_guid,
                location_guid=guid_row.location_guid,
                is_follow_on=is_follow_on,
                weeks=weeks,
                cutoff=cutoff,
            )
            logger.info(
                "Direct API: %s / %s / %s -> %d slots",
                guid_row.location_name, appt_type, guid_row.funding_route, len(location_slots),
            )
            all_slots.extend(location_slots)

    return all_slots


async def _fetch_all_weeks(
    context: BrowserContext,
    consultant_id: int,
    consultant_name: str,
    profile_url: str,
    location_name: str,
    funding_route: str,
    appointment_type: str,
    consultant_guid: str,
    location_guid: str,
    is_follow_on: str,
    weeks: list[tuple[str, str]],
    cutoff: datetime,
) -> list[SlotRecord]:
    slots: list[SlotRecord] = []

    for week_num, (date_from, date_to) in enumerate(weeks, 1):
        params = {
            "dateFrom": date_from,
            "dateTo": date_to,
            "isFollowOnAppointment": is_follow_on,
            "consultantGUID": consultant_guid,
            "locationGUID": location_guid,
        }
        url = f"{_BASE_API}?{urlencode(params)}"

        try:
            response = await context.request.get(url)
            data = _json.loads(await response.text())

            ep = CandidateEndpoint(
                url=url,
                method="GET",
                query_params=params,
                request_body=None,
                response_status=response.status,
                response_json=data,
                timing_ms=0,
                looks_like_slots=True,
            )
            week_slots = extract_from_api(
                ep,
                consultant_id=consultant_id,
                consultant_name=consultant_name,
                profile_url=profile_url,
                location_name=location_name,
                appointment_type=appointment_type,
                funding_route=funding_route,
            )
            week_slots = [s for s in week_slots if s.slot_datetime <= cutoff]
            logger.debug(
                "  week %d (%s to %s): %d slot(s)", week_num, date_from, date_to, len(week_slots)
            )
            slots.extend(week_slots)

        except Exception as e:
            logger.warning(
                "Direct API week %d failed (%s, %s): %s", week_num, location_name, date_from, e
            )

        await asyncio.sleep(0.2)

    return slots
