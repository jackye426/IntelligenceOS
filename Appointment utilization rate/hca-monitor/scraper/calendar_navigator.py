"""
Collect appointment slots for all weeks in the lookahead window.

Primary strategy: intercept the GetLDBConsultantSlots API call that fires on initial
page load, extract consultantGUID / locationGUID, then replay the request for every
week up to MAX_LOOKAHEAD_DAYS. This is far more reliable than clicking a next-week
button whose selector changes between HCA deployments.

Fallback: click the next-week chevron button and collect from each rendered page.
"""

import asyncio
import json as _json
import logging
from datetime import datetime, timedelta, timezone
from math import ceil
from urllib.parse import parse_qs, urlencode, urlparse

from playwright.async_api import Page

from config.settings import settings
from scraper.network_interceptor import CandidateEndpoint, NetworkInterceptor
from scraper.screenshot_manager import save_screenshot
from scraper.slot_extractor import SlotRecord, extract_from_api, extract_from_dom

logger = logging.getLogger(__name__)

# Selectors tried in order for "next week" pagination (fallback only)
_NEXT_SELECTORS = [
    "button[aria-label*='next' i]",
    "button[aria-label*='forward' i]",
    "[data-testid='calendar-next']",
    "[data-testid='next-month']",
    "[data-testid='next-week']",
    "button:has-text('›')",
    "button:has-text('>')",
    "button:has-text('»')",
    ".calendar-next",
    ".fc-next-button",
    "button.next",
    "a.next",
    "[class*='next'][role='button']",
]


async def collect_all_slots(
    page: Page,
    interceptor: NetworkInterceptor,
    consultant_id: int,
    consultant_name: str,
    profile_url: str,
    location_name: str,
    appointment_type: str,
    funding_route: str,
) -> list[SlotRecord]:
    """Collect all slots up to MAX_LOOKAHEAD_DAYS. Tries direct API first, falls back to pagination."""
    collection_ts = datetime.now(timezone.utc)
    cutoff = collection_ts + timedelta(days=settings.max_lookahead_days)

    common_args = dict(
        consultant_id=consultant_id,
        consultant_name=consultant_name,
        profile_url=profile_url,
        location_name=location_name,
        appointment_type=appointment_type,
        funding_route=funding_route,
    )

    # Wait for the slot page to hydrate and the first API call to fire
    await _wait_for_slots_rendered(page)
    await save_screenshot(page, f"calendar_{location_name[:20]}_{appointment_type[:10]}_p1")

    # Strategy 1: replay GetLDBConsultantSlots for every week (no UI interaction needed)
    api_slots = await _collect_via_direct_api(page, interceptor, collection_ts, cutoff, common_args)
    if api_slots is not None:
        logger.info(
            "Direct API: %d total slots for %s / %s",
            len(api_slots), location_name, appointment_type,
        )
        return _deduplicate(api_slots)

    # Strategy 2: click next-week button on each rendered page
    logger.info("GetLDBConsultantSlots not detected — falling back to button-click pagination")
    button_slots = await _collect_via_button_click(page, interceptor, collection_ts, cutoff, common_args)
    return _deduplicate(button_slots)


# ---------------------------------------------------------------------------
# Direct API strategy
# ---------------------------------------------------------------------------

async def _collect_via_direct_api(
    page: Page,
    interceptor: NetworkInterceptor,
    collection_ts: datetime,
    cutoff: datetime,
    common_args: dict,
) -> list[SlotRecord] | None:
    """
    Detect GetLDBConsultantSlots in intercepted requests, then replay for each week.
    Returns None if the API wasn't captured (triggers button-click fallback).
    """
    # Give the interceptor a moment to record the initial API call
    await asyncio.sleep(0.5)

    # Use the MOST RECENT GetLDBConsultantSlots call (reversed order) so each
    # location gets its own locationGUID, not the first location's.
    base_url: str | None = None
    base_params: dict = {}
    for ep in reversed(interceptor.get_candidate_endpoints()):
        if "GetLDBConsultantSlots" in ep.url:
            parsed = urlparse(ep.url)
            params = parse_qs(parsed.query, keep_blank_values=True)
            base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            base_params = {k: v[0] for k, v in params.items()}
            logger.info("GetLDBConsultantSlots detected: %s  params=%s", base_url, base_params)
            break

    if not base_url:
        return None

    all_slots: list[SlotRecord] = []
    max_weeks = settings.max_lookahead_days // 7 + 2

    # Start from the Monday of the current week
    week_start = collection_ts.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start -= timedelta(days=week_start.weekday())

    for week_num in range(max_weeks):
        if week_start > cutoff:
            logger.info("All weeks checked up to cutoff (%s)", cutoff.date())
            break

        week_end = week_start + timedelta(days=6)
        week_params = {
            **base_params,
            "dateFrom": week_start.strftime("%Y-%m-%d"),
            "dateTo": week_end.strftime("%Y-%m-%d"),
        }
        url = f"{base_url}?{urlencode(week_params)}"

        logger.info(
            "API week %d/%d: %s to %s",
            week_num + 1, max_weeks, week_params["dateFrom"], week_params["dateTo"],
        )
        try:
            response = await page.context.request.get(url)
            data = _json.loads(await response.text())

            ep = CandidateEndpoint(
                url=url,
                method="GET",
                query_params=week_params,
                request_body=None,
                response_status=response.status,
                response_json=data,
                timing_ms=0,
                looks_like_slots=True,
            )
            week_slots = extract_from_api(ep, **common_args)
            week_slots = [s for s in week_slots if s.slot_datetime <= cutoff]
            logger.info("API week %d: %d slot(s)", week_num + 1, len(week_slots))
            all_slots.extend(week_slots)

        except Exception as e:
            logger.warning("API week %d fetch failed (%s): %s", week_num + 1, week_start.date(), e)

        week_start += timedelta(days=7)
        await asyncio.sleep(0.3)  # polite pacing between API calls

    return all_slots


# ---------------------------------------------------------------------------
# Button-click fallback strategy
# ---------------------------------------------------------------------------

async def _collect_via_button_click(
    page: Page,
    interceptor: NetworkInterceptor,
    collection_ts: datetime,
    cutoff: datetime,
    common_args: dict,
) -> list[SlotRecord]:
    """Original fallback: page forward by clicking the next-week chevron."""
    all_slots: list[SlotRecord] = []
    max_pages = ceil(settings.max_lookahead_days / 7) + 1
    empty_consecutive = 0
    page_num = 0

    while page_num < max_pages:
        page_num += 1

        if page_num > 1:
            await _wait_for_slots_rendered(page)
            await save_screenshot(
                page,
                f"calendar_{common_args['location_name'][:20]}_{common_args['appointment_type'][:10]}_p{page_num}",
            )

        # Page 1: try captured API response; subsequent pages: DOM only
        # (interceptor.get_slot_api_response returns the first/best match — doesn't reset per page)
        if page_num == 1:
            api_endpoint = interceptor.get_slot_api_response()
            page_slots = extract_from_api(api_endpoint, **common_args) if api_endpoint else []
        else:
            page_slots = []

        if not page_slots:
            page_slots = await extract_from_dom(page, **common_args)

        page_slots = [s for s in page_slots if s.slot_datetime <= cutoff]

        if page_slots:
            logger.info("Page %d: %d slots", page_num, len(page_slots))
            all_slots.extend(page_slots)
            empty_consecutive = 0
        else:
            empty_consecutive += 1
            logger.debug("Page %d: no slots (empty_consecutive=%d)", page_num, empty_consecutive)

        if empty_consecutive >= settings.max_empty_calendar_pages:
            logger.info("Stopping: %d consecutive empty calendar pages", empty_consecutive)
            break

        if page_slots and all(s.slot_datetime > cutoff for s in page_slots):
            logger.info("Stopping: all slots beyond lookahead cutoff (%s)", cutoff.date())
            break

        moved = await _click_next(page)
        if not moved:
            logger.info("Stopping: no 'next' button found or it is disabled")
            break

    return all_slots


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deduplicate(slots: list[SlotRecord]) -> list[SlotRecord]:
    seen: set = set()
    unique: list[SlotRecord] = []
    for s in slots:
        key = (s.consultant_id, s.location_name, s.appointment_type, s.funding_route, s.slot_datetime)
        if key not in seen:
            seen.add(key)
            unique.append(s)
    logger.info("Dedup: %d -> %d unique slots", len(slots), len(unique))
    return unique


async def _wait_for_slots_rendered(page: Page) -> None:
    """Wait until slot time buttons (e.g. '9:00', '10:40') appear in the DOM."""
    try:
        await page.wait_for_function(
            r"Array.from(document.querySelectorAll('button')).some(b => /^\d{1,2}:\d{2}$/.test((b.textContent||'').trim()))",
            timeout=15000,
        )
        logger.debug("Slot buttons detected in DOM")
    except Exception:
        # No slots visible this week — valid (e.g. no availability); don't fail
        await asyncio.sleep(1)


async def _click_next(page: Page) -> bool:
    """Find and click the next-week button. Returns True if clicked."""
    for selector in _NEXT_SELECTORS:
        try:
            btn = page.locator(selector).first
            if await btn.count() == 0:
                continue
            disabled = await btn.get_attribute("disabled")
            aria_disabled = await btn.get_attribute("aria-disabled")
            if disabled is not None or aria_disabled == "true":
                logger.debug("Next button disabled (selector=%s)", selector)
                return False
            await btn.click()
            try:
                await page.wait_for_load_state("networkidle", timeout=settings.nav_timeout_ms)
            except Exception:
                await asyncio.sleep(1)
            logger.debug("Clicked next-week button via '%s'", selector)
            return True
        except Exception as e:
            logger.debug("Selector '%s' failed: %s", selector, e)

    return False
