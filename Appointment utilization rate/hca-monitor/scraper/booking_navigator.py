"""
Orchestrate the HCA multi-step booking flow for a given consultant.

Flow:
  1. Navigate to consultant profile page
  2. Click "Book online"
  3. Dismiss cookie consent banner (once per context)
  4. Accept terms & conditions (on every path — each fresh navigation lands on T&C)
  5. Select appointment type (initial / follow-up)
  6. Discover all location cards shown by the booking flow and click each one
  7. Load calendar — interceptor captures API; calendar_navigator pages forward
  8. Return list[SlotRecord]

Stops BEFORE slot selection — never submits patient details or creates holds.

NOTE: Location names in the booking flow differ from profile page names. We iterate
all location cards the booking flow exposes, rather than matching against profile names.
"""

import asyncio
import logging
import re

from playwright.async_api import BrowserContext, Page

from config.settings import settings
from scraper.calendar_navigator import collect_all_slots
from scraper.network_interceptor import NetworkInterceptor
from scraper.profile_extractor import ConsultantProfile
from scraper.screenshot_manager import save_screenshot
from scraper.slot_extractor import SlotRecord

logger = logging.getLogger(__name__)

APPOINTMENT_TYPES = ["initial", "follow-up"]

_BOOK_ONLINE_SELECTORS = [
    "a:has-text('Book online')",
    "button:has-text('Book online')",
    "a:has-text('Book appointment')",
    "button:has-text('Book appointment')",
    "[data-testid='book-online']",
    ".book-online-btn",
    "a[href*='booking']",
]

_APPT_TYPE_PATTERNS = {
    "initial": re.compile(
        r"new\s*patient|initial|new\s*consultation|first\s*(appointment|visit)",
        re.IGNORECASE,
    ),
    "follow-up": re.compile(
        r"follow.?(up|on)|return(?:ing)?|existing\s*patient|review|subsequent",
        re.IGNORECASE,
    ),
}

# Location cards contain this text — used to count/identify cards
_MAPS_TEXT = "View location on Google Maps"


async def scrape_consultant(
    context: BrowserContext,
    profile: ConsultantProfile,
    consultant_id: int,
    terms_state: dict,
) -> list[SlotRecord]:
    """
    Iterate appointment types; within each type, click all location cards the
    booking flow exposes (names differ from profile page — don't match against profile).
    terms_state tracks {'cookie_dismissed': bool} across calls.
    """
    all_slots: list[SlotRecord] = []

    for appt_type in APPOINTMENT_TYPES:
        try:
            slots = await _scrape_appointment_type(
                context=context,
                profile=profile,
                consultant_id=consultant_id,
                appointment_type=appt_type,
                terms_state=terms_state,
            )
            all_slots.extend(slots)
        except Exception as e:
            logger.error(
                "Error scraping %s / %s: %s",
                profile.name, appt_type, e,
                exc_info=True,
            )

    return all_slots


async def _scrape_appointment_type(
    context: BrowserContext,
    profile: ConsultantProfile,
    consultant_id: int,
    appointment_type: str,
    terms_state: dict,
) -> list[SlotRecord]:
    """One page per appointment type; iterates all booking-flow location cards within."""
    page = await context.new_page()
    interceptor = NetworkInterceptor()
    interceptor.attach(page)

    try:
        logger.info("Starting flow: %s / %s", profile.name, appointment_type)

        # Step 1: Profile page
        await page.goto(profile.profile_url, wait_until="domcontentloaded", timeout=30000)

        # Step 2: Click "Book online"
        booked = await _click_book_online(page)
        if not booked:
            logger.warning("Could not find 'Book online' button on %s", profile.profile_url)
            return []
        await _wait_for_navigation(page)
        logger.info("URL after Book online click: %s", page.url)

        # Step 3: Dismiss cookie consent banner (once per browser context)
        if not terms_state.get("cookie_dismissed"):
            dismissed = await _dismiss_cookie_consent(page)
            if dismissed:
                terms_state["cookie_dismissed"] = True
                logger.info("Cookie consent dismissed")
                await asyncio.sleep(0.5)

        # Step 4: Accept T&C — always run; each fresh navigation lands on T&C
        await save_screenshot(page, f"tc_page_{appointment_type[:8]}")
        accepted = await _accept_tc(page)
        if not accepted:
            logger.warning("Could not accept T&C (URL: %s)", page.url)
            return []
        try:
            await page.wait_for_url(
                re.compile(r"step-appointment-type|step-location|step-slot", re.IGNORECASE),
                timeout=15000,
            )
        except Exception:
            await _wait_for_navigation(page)
        logger.info("URL after T&C accept: %s", page.url)

        # Step 5: Select appointment type
        selected = await _select_appointment_type(page, appointment_type)
        if not selected:
            logger.warning(
                "Could not select appointment type '%s' (URL: %s)",
                appointment_type, page.url,
            )
            await _log_visible_elements(page)
            return []
        await _wait_for_navigation(page)
        logger.info("URL after appt type select: %s", page.url)
        await save_screenshot(page, f"location_page_{appointment_type[:8]}")

        # Step 6: Discover all location cards
        location_names = await _get_location_card_names(page)
        if not location_names:
            logger.warning(
                "No location cards found on location page (URL: %s)", page.url
            )
            return []
        logger.info("Found %d location card(s): %s", len(location_names), location_names)

        # Step 7+8: Click each card, collect slots, navigate back
        all_slots: list[SlotRecord] = []
        for card_idx, location_name in enumerate(location_names):
            try:
                clicked = await _click_location_card(page, card_idx)
                if not clicked:
                    logger.warning("Could not click location card %d: %s", card_idx, location_name)
                    continue
                await _wait_for_navigation(page)
                logger.info("URL after location select (%s): %s", location_name, page.url)

                funding_route = await _detect_funding_route(page)

                slots = await collect_all_slots(
                    page=page,
                    interceptor=interceptor,
                    consultant_id=consultant_id,
                    consultant_name=profile.name,
                    profile_url=profile.profile_url,
                    location_name=location_name,
                    appointment_type=appointment_type,
                    funding_route=funding_route,
                )
                logger.info(
                    "Collected %d slots: %s / %s / %s",
                    len(slots), profile.name, location_name, appointment_type,
                )
                all_slots.extend(slots)

                # Navigate back to location selection for next card
                if card_idx < len(location_names) - 1:
                    await page.go_back()
                    try:
                        await page.wait_for_url(
                            re.compile(r"step-location-select", re.IGNORECASE),
                            timeout=10000,
                        )
                    except Exception:
                        await _wait_for_navigation(page)
                    # Wait for location cards to re-render
                    await _wait_for_location_cards(page)

            except Exception as e:
                logger.error(
                    "Error on location card %d (%s): %s",
                    card_idx, location_name, e,
                    exc_info=True,
                )
                # Try to recover back to location selection
                try:
                    await page.go_back()
                    await _wait_for_navigation(page)
                except Exception:
                    pass

        return all_slots

    finally:
        await page.close()


async def _click_book_online(page: Page) -> bool:
    for selector in _BOOK_ONLINE_SELECTORS:
        try:
            btn = page.locator(selector).first
            if await btn.count() > 0:
                await btn.click()
                return True
        except Exception as e:
            logger.debug("Book online selector '%s' failed: %s", selector, e)
    return False


async def _dismiss_cookie_consent(page: Page) -> bool:
    """Dismiss the Google/cookie consent overlay if present."""
    cookie_selectors = [
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept all cookies')",
        "button:has-text('Accept all')",
        "[data-testid='accept-all']",
        ".cookie-accept-all",
    ]
    for selector in cookie_selectors:
        try:
            btn = page.locator(selector).first
            if await btn.count() > 0:
                await btn.click()
                logger.debug("Cookie consent dismissed via '%s'", selector)
                return True
        except Exception as e:
            logger.debug("Cookie selector '%s' failed: %s", selector, e)
    return False


async def _accept_tc(page: Page) -> bool:
    """
    Accept the HCA T&C page.
    The Accept button has exact text 'Accept' (not 'Accept All Cookies').
    Returns True immediately if not on the T&C page.
    """
    url = page.url
    if "step-terms" not in url.lower() and "terms-and-condition" not in url.lower():
        logger.debug("Not on T&C page (URL: %s) — skipping", url)
        return True

    await asyncio.sleep(1)

    for attempt in (
        page.get_by_role("button", name=re.compile(r"^\s*Accept\s*$")),
        page.locator("button, a, [role='button']").filter(
            has_text=re.compile(r"^\s*Accept\s*$")
        ),
    ):
        try:
            if await attempt.count() > 0:
                btn = attempt.first
                await btn.scroll_into_view_if_needed()
                await btn.click()
                logger.info("T&C Accept button clicked")
                return True
        except Exception as e:
            logger.debug("T&C accept attempt failed: %s", e)

    # Fallback: iterate all buttons, skip cookie-related ones
    _cookie_pattern = re.compile(r"cookie|all|choice|preference|confirm", re.IGNORECASE)
    all_buttons = page.get_by_role("button")
    count = await all_buttons.count()
    for i in range(count):
        try:
            btn = all_buttons.nth(i)
            text = (await btn.text_content() or "").strip()
            if text.lower() == "accept" and not _cookie_pattern.search(text):
                await btn.scroll_into_view_if_needed()
                await btn.click()
                logger.info("T&C Accept button clicked via loop (text: '%s')", text)
                return True
        except Exception as e:
            logger.debug("T&C button %d failed: %s", i, e)

    logger.warning("Could not find T&C Accept button (URL: %s)", url)
    return False


async def _select_appointment_type(page: Page, appointment_type: str) -> bool:
    pattern = _APPT_TYPE_PATTERNS.get(appointment_type, re.compile(appointment_type, re.IGNORECASE))

    # Wait for Next.js to hydrate
    try:
        await page.wait_for_function(
            "Array.from(document.querySelectorAll('button, a, li')).some(el => el.textContent.trim().length > 3)",
            timeout=15000,
        )
    except Exception:
        await asyncio.sleep(3)

    for role in ("button", "link"):
        try:
            els = page.get_by_role(role)
            count = await els.count()
            for i in range(count):
                text = (await els.nth(i).text_content() or "").strip()
                if pattern.search(text):
                    await els.nth(i).click()
                    logger.info("Selected appointment type '%s' via text '%s'", appointment_type, text[:60])
                    return True
        except Exception:
            pass

    all_els = page.locator("button, a, li, [role='option'], .appointment-type, [class*='type']")
    count = await all_els.count()
    for i in range(count):
        try:
            text = (await all_els.nth(i).text_content() or "").strip()
            if pattern.search(text):
                await all_els.nth(i).click()
                logger.info("Selected appointment type '%s' via fallback text '%s'", appointment_type, text[:60])
                return True
        except Exception:
            pass

    return False


async def _wait_for_location_cards(page: Page) -> None:
    """Wait until location cards are rendered (Next.js hydration)."""
    # Wait for either a Maps link OR a weekday-date pattern (not all cards have Maps links)
    try:
        await page.wait_for_function(
            r"""document.body.innerText.includes('View location on Google Maps') ||
                /\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+\d{1,2}\s+\w+\s+\d{4}/.test(document.body.innerText)""",
            timeout=15000,
        )
    except Exception:
        await asyncio.sleep(2)


async def _get_location_card_names(page: Page) -> list[str]:
    """
    Extract location names from all booking-flow location cards.

    Strategy 1: JS — find leaf elements whose text matches a weekday-date pattern
    ("Friday, 29 May 2026"), walk up the DOM to find the card's h2/h3 heading.
    Works for cards that lack a Google Maps link.

    Strategy 2: Fallback — anchor on 'View location on Google Maps' links and walk up.
    """
    await _wait_for_location_cards(page)

    # Strategy 1: date-pattern JS scan
    names: list[str] = await page.evaluate(r"""() => {
        const datePat = /^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}$/;
        const results = [];
        const seen = new Set();
        document.querySelectorAll('*').forEach(el => {
            if (el.children.length > 0) return;
            const text = (el.textContent || '').trim();
            if (!datePat.test(text)) return;
            let node = el;
            for (let i = 0; i < 10; i++) {
                node = node.parentElement;
                if (!node) break;
                const h = node.querySelector('h2, h3, h4');
                if (h) {
                    const name = (h.textContent || '').trim();
                    if (name && name.length > 3 && !seen.has(name)) {
                        seen.add(name);
                        results.push(name);
                    }
                    break;
                }
            }
        });
        return results;
    }""")

    # Strategy 2: Maps-link fallback (catches cards with no date shown yet)
    if not names:
        maps_links = page.get_by_text(_MAPS_TEXT)
        count = await maps_links.count()
        for i in range(count):
            try:
                link = maps_links.nth(i)
                for levels in range(2, 8):
                    ancestor_xpath = "/".join([".."] * levels)
                    ancestor = link.locator(f"xpath={ancestor_xpath}")
                    heading = ancestor.locator("h2, h3").first
                    if await heading.count() > 0:
                        text = (await heading.text_content() or "").strip()
                        if text and len(text) > 5:
                            names.append(text)
                            break
            except Exception as e:
                logger.debug("Maps-link fallback card %d failed: %s", i, e)

    logger.debug("Location card names extracted: %s", names)
    return names


async def _click_location_card(page: Page, card_index: int) -> bool:
    """
    Click the nth location card by finding its heading and clicking it.
    Uses _get_location_card_names() to discover all cards (not just those with Maps links).
    """
    names = await _get_location_card_names(page)
    if card_index >= len(names):
        logger.debug("Card index %d out of range (found %d cards)", card_index, len(names))
        return False

    target = names[card_index]

    # Find the matching heading and click it
    all_headings = page.locator("h2, h3, h4")
    count = await all_headings.count()
    for i in range(count):
        try:
            text = (await all_headings.nth(i).text_content() or "").strip()
            if text == target:
                heading = all_headings.nth(i)
                await heading.scroll_into_view_if_needed()
                await heading.click()
                logger.info("Clicked location card %d: %s", card_index, target)
                return True
        except Exception as e:
            logger.debug("Heading click attempt %d failed: %s", i, e)

    # Fallback: click via JS using exact text match
    try:
        clicked = await page.evaluate(
            """(name) => {
                const els = Array.from(document.querySelectorAll('h2, h3, h4'));
                const el = els.find(e => (e.textContent || '').trim() === name);
                if (el) { el.click(); return true; }
                return false;
            }""",
            target,
        )
        if clicked:
            logger.info("Clicked location card %d via JS: %s", card_index, target)
            return True
    except Exception as e:
        logger.debug("JS click fallback failed: %s", e)

    return False


async def _detect_funding_route(page: Page) -> str:
    try:
        body = await page.content()
        if re.search(r"self.?pay", body, re.IGNORECASE):
            sel_el = page.locator(".self-pay.active, [data-funding='self-pay'], button.active:has-text('self')").first
            if await sel_el.count() > 0:
                return "self-pay"
        if re.search(r"insur|private\s+health", body, re.IGNORECASE):
            return "insured"
    except Exception:
        pass
    return "unknown"


async def _log_visible_elements(page: Page) -> None:
    """Log visible interactive element texts for debugging."""
    try:
        texts = []
        for role in ("button", "link"):
            els = page.get_by_role(role)
            count = await els.count()
            for i in range(min(count, 10)):
                t = (await els.nth(i).text_content() or "").strip()
                if t:
                    texts.append(repr(t[:80]))
        logger.info("Visible interactive elements: %s", ", ".join(texts) or "(none)")
    except Exception as e:
        logger.debug("Could not log elements: %s", e)


async def _wait_for_navigation(page: Page) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=settings.nav_timeout_ms)
    except Exception:
        await asyncio.sleep(1)
