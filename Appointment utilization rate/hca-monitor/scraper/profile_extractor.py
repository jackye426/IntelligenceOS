"""
Extract static consultant profile data from an HCA consultant profile page.

Returns a ConsultantProfile dataclass and a list of LocationRecord dataclasses.
All parsing is done against the rendered DOM — no API calls needed here.
"""

import logging
import re
from dataclasses import dataclass, field

from playwright.async_api import Page

from scraper.screenshot_manager import save_screenshot

logger = logging.getLogger(__name__)


@dataclass
class LocationRecord:
    location_name: str
    address: str | None = None
    published_days: list[str] = field(default_factory=list)
    published_hours: str | None = None
    is_available_on_profile: bool = False


@dataclass
class ConsultantProfile:
    name: str
    profile_url: str
    specialty: str | None = None
    gmc_number: str | None = None
    review_count: int | None = None
    new_appointment_fee: str | None = None
    follow_up_fee: str | None = None
    locations: list[LocationRecord] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    procedures: list[str] = field(default_factory=list)


async def extract_profile(page: Page, profile_url: str) -> ConsultantProfile:
    """Navigate to the profile URL and extract all static baseline fields."""
    logger.info("Extracting profile from %s", profile_url)
    await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
    await save_screenshot(page, "profile_page")

    name = await _extract_name(page)
    specialty = await _extract_specialty(page)
    gmc_number = await _extract_gmc(page)
    review_count = await _extract_review_count(page)
    new_fee, follow_up_fee = await _extract_fees(page)
    locations = await _extract_locations(page)
    conditions, procedures = await _extract_conditions_procedures(page)

    profile = ConsultantProfile(
        name=name or "Unknown",
        profile_url=profile_url,
        specialty=specialty,
        gmc_number=gmc_number,
        review_count=review_count,
        new_appointment_fee=new_fee,
        follow_up_fee=follow_up_fee,
        locations=locations,
        conditions=conditions,
        procedures=procedures,
    )
    logger.info("Profile extracted: %s, %d location(s)", profile.name, len(profile.locations))
    return profile


async def _extract_name(page: Page) -> str | None:
    selectors = [
        "h1",
        ".consultant-name",
        "[data-testid='consultant-name']",
        ".profile-name",
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                text = (await el.text_content() or "").strip()
                if text:
                    return text
        except Exception:
            pass
    return None


async def _extract_specialty(page: Page) -> str | None:
    selectors = [
        ".consultant-specialty",
        ".specialty",
        "[data-testid='specialty']",
        ".profile-specialty",
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                text = (await el.text_content() or "").strip()
                if text:
                    return text
        except Exception:
            pass
    # Fallback: look for text near "Specialty" label
    try:
        body = await page.content()
        m = re.search(r"Specialty[:\s]+([A-Za-z &,/]+)", body)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return None


async def _extract_gmc(page: Page) -> str | None:
    selectors = [
        ".gmc-number",
        "[data-testid='gmc']",
        ".profile-gmc",
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                text = (await el.text_content() or "").strip()
                m = re.search(r"\d{7}", text)
                if m:
                    return m.group(0)
        except Exception:
            pass
    # Fallback: scan page text for 7-digit GMC
    try:
        body = await page.content()
        m = re.search(r"GMC[:\s#]*(\d{7})", body)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


async def _extract_review_count(page: Page) -> int | None:
    selectors = [
        ".review-count",
        ".rating-count",
        "[data-testid='review-count']",
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                text = (await el.text_content() or "").strip()
                m = re.search(r"(\d+)", text)
                if m:
                    return int(m.group(1))
        except Exception:
            pass
    try:
        body = await page.content()
        m = re.search(r"(\d+)\s+review", body, re.IGNORECASE)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


async def _extract_fees(page: Page) -> tuple[str | None, str | None]:
    new_fee = None
    follow_up = None
    try:
        body = await page.content()
        m = re.search(r"[Ii]nitial\s+[Cc]onsultation[:\s]+([£$€\d,\. ]+)", body)
        if m:
            new_fee = m.group(1).strip()
        m2 = re.search(r"[Ff]ollow.?[Uu]p[:\s]+([£$€\d,\. ]+)", body)
        if m2:
            follow_up = m2.group(1).strip()
        # Also try structured fee elements
        fee_els = page.locator(".fee, .price, [data-testid='fee']")
        count = await fee_els.count()
        for i in range(count):
            text = (await fee_els.nth(i).text_content() or "").strip()
            if "initial" in text.lower() and not new_fee:
                new_fee = text
            elif "follow" in text.lower() and not follow_up:
                follow_up = text
    except Exception:
        pass
    return new_fee, follow_up


async def _extract_locations(page: Page) -> list[LocationRecord]:
    locations: list[LocationRecord] = []
    try:
        # HCA profiles typically list locations in a section
        location_containers = page.locator(
            ".location-item, .consulting-location, [data-testid='location'], .clinic-location"
        )
        count = await location_containers.count()
        for i in range(count):
            el = location_containers.nth(i)
            loc = await _parse_location_element(el)
            if loc:
                locations.append(loc)
    except Exception as e:
        logger.warning("Structured location extraction failed: %s", e)

    if not locations:
        # Fallback: look for any element containing a known HCA hospital name
        locations = await _fallback_location_extraction(page)

    logger.info("Extracted %d location(s)", len(locations))
    return locations


async def _parse_location_element(el) -> LocationRecord | None:
    try:
        name_el = el.locator(".location-name, h3, h4, strong").first
        name = ""
        if await name_el.count() > 0:
            name = (await name_el.text_content() or "").strip()
        if not name:
            name = (await el.text_content() or "").strip()[:100]
        if not name:
            return None

        address = None
        addr_el = el.locator(".address, .location-address").first
        if await addr_el.count() > 0:
            address = (await addr_el.text_content() or "").strip()

        published_hours = None
        hours_el = el.locator(".hours, .consulting-hours, .times").first
        if await hours_el.count() > 0:
            published_hours = (await hours_el.text_content() or "").strip()

        published_days = _parse_days_from_text(published_hours or "")

        book_btn = el.locator("a, button").filter(has_text=re.compile(r"book", re.IGNORECASE))
        is_available = await book_btn.count() > 0

        return LocationRecord(
            location_name=name,
            address=address,
            published_days=published_days,
            published_hours=published_hours,
            is_available_on_profile=is_available,
        )
    except Exception:
        return None


async def _fallback_location_extraction(page: Page) -> list[LocationRecord]:
    known_locations = [
        "The Lister Hospital",
        "The Harley Street Clinic",
        "The Portland Hospital",
        "The Wellington Hospital",
        "The Princess Grace Hospital",
        "The Wilmslow Hospital",
        "The Syon Clinic",
        "The Christie Clinic",
        "Roodlane Medical",
        "HCA UK",
    ]
    locations = []
    try:
        body = await page.content()
        for loc_name in known_locations:
            if loc_name.lower() in body.lower():
                locations.append(LocationRecord(
                    location_name=loc_name,
                    is_available_on_profile=True,
                ))
    except Exception:
        pass
    return locations


def _parse_days_from_text(text: str) -> list[str]:
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    abbrevs = {
        "Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday",
        "Thu": "Thursday", "Fri": "Friday", "Sat": "Saturday", "Sun": "Sunday",
    }
    found = []
    for day in day_names:
        if day.lower() in text.lower() or day[:3].lower() in text.lower():
            if day not in found:
                found.append(day)
    for abbr, full in abbrevs.items():
        if abbr.lower() in text.lower() and full not in found:
            found.append(full)
    return found


async def _extract_conditions_procedures(page: Page) -> tuple[list[str], list[str]]:
    conditions: list[str] = []
    procedures: list[str] = []
    try:
        cond_els = page.locator(".conditions li, .condition-tag, [data-testid='condition']")
        for i in range(await cond_els.count()):
            text = (await cond_els.nth(i).text_content() or "").strip()
            if text:
                conditions.append(text)
        proc_els = page.locator(".procedures li, .procedure-tag, [data-testid='procedure']")
        for i in range(await proc_els.count()):
            text = (await proc_els.nth(i).text_content() or "").strip()
            if text:
                procedures.append(text)
    except Exception:
        pass
    return conditions, procedures
