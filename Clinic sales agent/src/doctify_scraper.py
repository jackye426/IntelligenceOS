"""
Scrapes Doctify listing pages for clinic/practice cards.

Primary strategy: intercept JSON API responses that Doctify fires when it
loads search results (it's a React SPA). This gives structured data without
any CSS-selector fragility.

Fallback: DOM scraping with BeautifulSoup if no API data is captured.

For clinic profiles: DOM scraping to find the external website URL.
"""

import asyncio
import re
from urllib.parse import urlparse, urlunparse

from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from config import REQUEST_DELAY
from utils import log


def _build_page_url(base_url: str, page_num: int) -> str:
    """
    Doctify uses path-based pagination:
      page 1:  /practices#distance=5
      page 2:  /practices/page-2#distance=5
    """
    parsed = urlparse(base_url)
    path = re.sub(r'/page-\d+$', '', parsed.path.rstrip('/'))
    if page_num > 1:
        path = f"{path}/page-{page_num}"
    return urlunparse(parsed._replace(path=path))


_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/120.0.0.0 Safari/537.36'
)


async def _scrape_listings_for_url(browser, cfg: dict, skip_profiles: set,
                                    listing_delay: float) -> list:
    """Scrape all listing pages for one URL. Returns clinic stubs (no profile data)."""
    ctx = await browser.new_context(user_agent=_UA, viewport={'width': 1280, 'height': 800})
    page = await ctx.new_page()
    stubs = []
    cookies_dismissed = False
    consecutive_empty = 0
    label = cfg['url'].split('/find/')[-1].split('/')[0]

    try:
        for page_num in range(1, cfg['pages'] + 1):
            url = _build_page_url(cfg['url'], page_num)
            captured_api = []

            async def _on_resp(response, _buf=captured_api):
                if response.status != 200:
                    return
                if 'json' not in response.headers.get('content-type', ''):
                    return
                if '/webapi/' not in response.url and '/api/' not in response.url:
                    return
                try:
                    body = await response.json()
                    results = _extract_clinics_from_json(body)
                    if results:
                        _buf.extend(results)
                except Exception:
                    pass

            page.on('response', _on_resp)
            try:
                await page.goto(url, wait_until='networkidle', timeout=30000)
            except Exception:
                try:
                    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                    await asyncio.sleep(3)
                except Exception as e:
                    log(f"  [{label} p{page_num}] nav failed: {e}")
                    page.remove_listener('response', _on_resp)
                    continue

            if not cookies_dismissed:
                await _dismiss_cookies(page)
                cookies_dismissed = True

            await asyncio.sleep(1.5)
            page.remove_listener('response', _on_resp)

            if captured_api:
                seen_keys = set()
                found = []
                for c in captured_api:
                    key = c.get('doctify_profile_url', '')
                    if key and key not in seen_keys and key not in skip_profiles:
                        seen_keys.add(key)
                        found.append(c)
            else:
                found = [c for c in await _dom_scrape(page)
                         if c.get('doctify_profile_url', '') not in skip_profiles]

            if not found:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    log(f"  [{label}] 3 empty pages — stopping early at p{page_num}")
                    break
            else:
                consecutive_empty = 0
                stubs.extend(found)

            await asyncio.sleep(listing_delay)

        log(f"  [{label}] listing done — {len(stubs)} stubs")
    finally:
        await ctx.close()

    return stubs


async def _visit_one_profile(browser, clinic: dict) -> None:
    """Visit one Doctify profile and update clinic dict in place."""
    profile_url = clinic.get('doctify_profile_url', '')
    empty = {'website_url': '', 'contact_email': '', 'phone': '',
             'doctify_about': '', 'specialist_count': None}
    if not profile_url:
        clinic.update(empty)
        return

    ctx = await browser.new_context(user_agent=_UA, viewport={'width': 1280, 'height': 800})
    page = await ctx.new_page()
    try:
        contact = await _get_contact_from_profile(page, profile_url)
        clinic.update(contact)
    except Exception as e:
        log(f"    profile error ({clinic.get('clinic_name', '?')}): {e}")
        clinic.update(empty)
    finally:
        await ctx.close()


async def scrape_doctify(
    url_configs: list,
    skip_profile_urls: set = None,
    listing_delay: float = None,
    max_profile_concurrency: int = 4,
    on_clinic_ready=None,
) -> list:
    """
    Scraper for multiple Doctify URLs.

    Phase 1 — Listings:  sequential (one URL at a time) — Doctify rate-limits
                         concurrent listing requests aggressively.
    Phase 2 — Profiles:  up to `max_profile_concurrency` Doctify practice pages
                         at once (safe since each hits a different URL).

    on_clinic_ready: optional async callback(clinic) invoked after each profile visit.
    """
    if listing_delay is None:
        listing_delay = REQUEST_DELAY
    if skip_profile_urls is None:
        skip_profile_urls = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # ── Phase 1: listing pages (sequential per URL) ───────────────────────
        log(f"Phase 1: scraping {len(url_configs)} URLs sequentially")
        seen = set(skip_profile_urls)
        all_stubs = []

        for cfg in url_configs:
            stubs = await _scrape_listings_for_url(browser, cfg, seen, listing_delay)
            for stub in stubs:
                key = stub.get('doctify_profile_url', '')
                if key and key not in seen:
                    seen.add(key)
                    all_stubs.append(stub)

        log(f"\nPhase 1 done: {len(all_stubs)} unique clinics "
            f"(skipped {len(skip_profile_urls)} already in CSV)")

        # ── Phase 2: profile visits (parallel) ───────────────────────────────
        log(f"Phase 2: visiting {len(all_stubs)} profiles "
            f"({max_profile_concurrency} concurrent)")
        sem_prof = asyncio.Semaphore(max_profile_concurrency)
        done_lock = asyncio.Lock()
        done_count = [0]

        async def visit(clinic):
            async with sem_prof:
                await _visit_one_profile(browser, clinic)
            async with done_lock:
                done_count[0] += 1
                n = done_count[0]
                if n % 100 == 0 or n == len(all_stubs):
                    log(f"  Profiles: {n}/{len(all_stubs)}")
                if on_clinic_ready:
                    await on_clinic_ready(clinic)

        await asyncio.gather(*[visit(c) for c in all_stubs])
        await browser.close()

    return all_stubs


async def _dismiss_cookies(page):
    try:
        btn = page.locator(
            'button'
        ).filter(has_text=re.compile(r'accept|agree|ok|got it|allow', re.I)).first
        await btn.click(timeout=3000)
        await asyncio.sleep(0.5)
    except Exception:
        pass


async def _scrape_current_page(page) -> list:
    """Scrape whichever listing page is currently loaded in the browser."""
    captured = []

    async def on_response(response):
        if response.status != 200:
            return
        if 'json' not in response.headers.get('content-type', ''):
            return
        try:
            body = await response.json()
            results = _extract_clinics_from_json(body)
            if results:
                log(f"  [API] {len(results)} items from {response.url}")
                captured.extend(results)
        except Exception:
            pass

    page.on('response', on_response)
    await asyncio.sleep(2)  # Let any delayed XHR fire
    page.remove_listener('response', on_response)

    if captured:
        seen = set()
        unique = []
        for c in captured:
            key = c.get('doctify_profile_url', '')
            if key and key not in seen:
                seen.add(key)
                unique.append(c)
        return unique

    return await _dom_scrape(page)


async def _click_next_page(page) -> bool:
    """Click the pagination 'next' button. Returns True if successful."""
    selectors = [
        # aria-label variants
        '[aria-label="Next page"]',
        '[aria-label="Next"]',
        '[aria-label="next"]',
        # data-testid variants
        '[data-testid*="next"]',
        '[data-testid*="pagination-next"]',
        # text-based
        'button:has-text("Next")',
        'a:has-text("Next")',
        # rel="next"
        'a[rel="next"]',
        # icon arrow buttons inside nav
        'nav button:last-child',
        'nav a:last-child',
        # generic pagination containers
        '[class*="pagination"] button:last-child',
        '[class*="Pagination"] button:last-child',
        '[class*="pagination"] a:last-child',
    ]

    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000) and await el.is_enabled(timeout=1000):
                await el.click()
                await page.wait_for_load_state('networkidle', timeout=15000)
                await asyncio.sleep(1)
                return True
        except Exception:
            continue

    return False


# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------

def _extract_clinics_from_json(data) -> list:
    """Recursively walk a JSON blob to find a list of clinic-like records."""

    def walk(obj, depth=0):
        if depth > 6:
            return []
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            if _looks_like_clinic_list(obj):
                return [_normalise_clinic(item) for item in obj if isinstance(item, dict)]
        if isinstance(obj, dict):
            for val in obj.values():
                found = walk(val, depth + 1)
                if found:
                    return found
        return []

    return walk(data)


def _looks_like_clinic_list(lst: list) -> bool:
    """True only if the list looks like practice/clinic records, not categories/specialties."""
    if not lst or len(lst) < 2:
        return False
    sample = lst[0]
    # Clinic records have many fields; specialty/category lists have ~4
    if not isinstance(sample, dict) or len(sample) < 8:
        return False

    # name must be a plain string OR a Doctify i18n dict {"en": "..."}
    name_val = sample.get('name') or sample.get('title') or sample.get('displayName')
    if name_val is not None and not isinstance(name_val, str):
        if not (isinstance(name_val, dict) and isinstance(name_val.get('en'), str)):
            return False

    # Must have at least one strong clinic-specific field (not present in category lists)
    strong_clinic_fields = {
        'address', 'averageRating', 'reviewsTotal', 'externalId', 'distance',
        'rating', 'reviewCount', 'review_count', 'totalReviews',
        'location', 'profileUrl', 'profile_url', 'latitude', 'longitude',
        'externalBookingLink', 'physicalLocation',
    }
    return bool(strong_clinic_fields & set(sample.keys()))


def _get(obj: dict, *keys):
    for k in keys:
        if k in obj:
            return obj[k]
        for actual in obj:
            if actual.lower() == k.lower():
                return obj[actual]
    return None


def _en(val) -> str:
    """Extract English string from Doctify's i18n dict {"en": "..."} or plain string."""
    if isinstance(val, dict):
        return str(val.get('en') or next(iter(val.values()), '') or '').strip()
    return str(val).strip() if val else ''


def _normalise_clinic(item: dict) -> dict:
    raw_name = _get(item, 'name', 'title', 'displayName', 'fullName', 'practiceName') or ''
    name = _en(raw_name)

    slug = _get(item, 'slug', 'urlSlug', 'url_slug') or ''
    profile = _get(item, 'profileUrl', 'profile_url', 'url', 'href', 'link', 'path') or ''

    if slug and not profile:
        profile = f"https://www.doctify.com/uk/practice/{slug}"
    elif profile and not profile.startswith('http'):
        profile = f"https://www.doctify.com{profile}"

    # Location — Doctify address fields are also i18n dicts
    loc = _get(item, 'location', 'address', 'practiceAddress') or {}
    if isinstance(loc, dict):
        location = ', '.join(filter(None, [
            _en(loc.get('city', '')),
            _en(loc.get('area', '')),
            _en(loc.get('postcode', '')),
        ]))
    else:
        location = str(loc) if loc else ''

    # Specialty tags — primary: Doctify keywords array (keywordType == "specialty")
    specialty_tags = []
    keywords = item.get('keywords', [])
    if isinstance(keywords, list):
        for kw in keywords:
            if isinstance(kw, dict) and kw.get('keywordType') == 'specialty':
                tag = _en(kw.get('name', ''))
                if tag:
                    specialty_tags.append(tag)

    # Fallback: legacy field names
    if not specialty_tags:
        specialties_raw = _get(item, 'specialties', 'specialisms', 'medicalSpecialties', 'tags', 'categories') or []
        if isinstance(specialties_raw, list):
            specialty_tags = [
                _en(s.get('name', '')) if isinstance(s, dict) else str(s)
                for s in specialties_raw
            ]
            specialty_tags = [s.strip() for s in specialty_tags if s.strip()]

    # Specialist count — from API 'specialists' field, or legacy field names
    raw_specialists = _get(
        item, 'specialists', 'practitionerCount', 'specialistCount', 'doctorCount',
        'totalPractitioners', 'numberOfPractitioners', 'totalDoctors', 'numberOfDoctors',
    )
    if isinstance(raw_specialists, list):
        specialist_count = len(raw_specialists) if raw_specialists else None
    else:
        specialist_count = raw_specialists

    return {
        'clinic_name': name,
        'doctify_profile_url': str(profile).strip(),
        'location': location.strip(),
        'rating': _get(item, 'rating', 'averageRating', 'score'),
        'review_count': _get(item, 'reviewCount', 'review_count', 'totalReviews', 'reviewsTotal'),
        'specialty_tags': specialty_tags,
        'specialist_count': specialist_count,
        'website_url': '',
    }


# ---------------------------------------------------------------------------
# DOM fallback
# ---------------------------------------------------------------------------

async def _dom_scrape(page) -> list:
    html = await page.content()

    # Next.js hydration payload — richest source, try first
    from_next = _extract_from_next_data(html)
    if from_next:
        log(f"  [__NEXT_DATA__] {len(from_next)} clinics extracted")
        return from_next

    soup = BeautifulSoup(html, 'lxml')
    clinics = []

    cards = (
        soup.select('[data-testid*="card"]')
        or soup.select('[class*="ProfileCard"]')
        or soup.select('[class*="ListingCard"]')
        or soup.select('[class*="result-card"]')
        or soup.select('[class*="practice-card"]')
        or soup.select('article')
    )

    for card in cards:
        profile_url = ''
        name = ''
        location = ''

        for a in card.find_all('a', href=True):
            href = a['href']
            if '/practice/' in href or '/specialist/' in href or '/doctor/' in href:
                profile_url = href
                break

        if not profile_url:
            continue

        if not profile_url.startswith('http'):
            profile_url = f"https://www.doctify.com{profile_url}"

        for tag in ['h1', 'h2', 'h3', 'h4', 'strong']:
            el = card.find(tag)
            if el:
                name = el.get_text(strip=True)
                break

        # Try to find location text (address/city span near the card)
        for hint in ['address', 'location', 'city', 'area']:
            el = card.find(class_=re.compile(hint, re.I))
            if el:
                location = el.get_text(strip=True)
                break
        if not location:
            # Fall back: look for a <p> that looks like a UK address
            for p in card.find_all('p'):
                text = p.get_text(strip=True)
                if re.search(r'\b(London|Street|Road|Avenue|W1|EC|SW|SE|NW|N\d)\b', text):
                    location = text
                    break

        card_text = card.get_text(separator=' ', strip=True)

        # "4 specialists" or "1 specialist"
        count_match = re.search(r'(\d+)\s+specialist', card_text, re.I)
        specialist_count = int(count_match.group(1)) if count_match else None

        # Specialty tags: text between "Specialties:" / "Specialisms:" and "View all" / end of section
        specialty_tags = []
        spec_match = re.search(
            r'Specialt(?:ies|y|isms?)[:\s]+(.+?)(?:View all|$)', card_text, re.I | re.DOTALL
        )
        if spec_match:
            raw = re.sub(r'\s+', ' ', spec_match.group(1)).strip()
            specialty_tags = [s.strip() for s in re.split(r'[,\n]', raw) if s.strip()]

        clinics.append({
            'clinic_name': name,
            'doctify_profile_url': profile_url,
            'location': location,
            'rating': None,
            'review_count': None,
            'specialty_tags': specialty_tags,
            'specialist_count': specialist_count,
            'website_url': '',
        })

    return clinics


def _extract_from_next_data(html: str) -> list:
    """Extract clinic list from Next.js __NEXT_DATA__ hydration blob."""
    import json as _json
    soup = BeautifulSoup(html, 'lxml')
    script = soup.find('script', id='__NEXT_DATA__')
    if not script or not script.string:
        return []
    try:
        data = _json.loads(script.string)
        return _extract_clinics_from_json(data)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Profile page — extract website URL
# ---------------------------------------------------------------------------

SKIP_DOMAINS = {
    'doctify.com', 'teamtailor.com', 'facebook.com', 'twitter.com', 'x.com',
    'instagram.com', 'linkedin.com', 'youtube.com', 'nhs.uk',
    'google.com', 'apple.com', 'trustpilot.com', 'healthgrades.com',
}


def _is_external(href: str) -> bool:
    if not href or not href.startswith('http'):
        return False
    domain = urlparse(href).netloc.replace('www.', '')
    return not any(s in domain for s in SKIP_DOMAINS)


async def _get_contact_from_profile(page, profile_url: str) -> dict:
    """
    Returns {'website_url': ..., 'contact_email': ..., 'phone': ..., 'doctify_about': ...}
    from a Doctify clinic profile page.
    """
    result = {'website_url': '', 'contact_email': '', 'phone': '', 'doctify_about': ''}

    try:
        await page.goto(profile_url, wait_until='networkidle', timeout=20000)
    except Exception:
        try:
            await page.goto(profile_url, wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(2)
        except Exception:
            return result

    await asyncio.sleep(1)
    html = await page.content()

    # __NEXT_DATA__: email, phone, website
    next_contact = _contact_from_next_data(html)
    result.update(next_contact)

    # DOM fallback for website
    if not result['website_url']:
        result['website_url'] = _website_from_dom(html)

    # About text: grab substantive <p> paragraphs before the reviews section
    result['doctify_about'] = _extract_about(html)

    # Specialist count: look for "X specialist(s)" or "team of X" in visible page text
    result['specialist_count'] = _extract_specialist_count(html)

    return result


def _website_from_dom(html: str) -> str:
    """DOM fallback for website URL when __NEXT_DATA__ doesn't have it."""
    soup = BeautifulSoup(html, 'lxml')

    for a in soup.find_all('a', href=True):
        href = a.get('href', '')
        text = a.get_text(strip=True).lower()
        if _is_external(href) and any(w in text for w in ['website', 'visit our', 'www.']):
            return href

    for a in soup.find_all('a', href=True):
        href = a.get('href', '')
        text = a.get_text(strip=True).lower()
        rel = ' '.join(a.get('rel', []))
        target = a.get('target', '')
        if _is_external(href) and (target == '_blank' or 'noopener' in rel):
            if any(w in text for w in ['book', 'appointment', 'visit', 'website', 'contact']):
                return href

    for section in soup.find_all(['section', 'div', 'aside']):
        classes = ' '.join(section.get('class', [])).lower()
        if not any(k in classes for k in ['contact', 'info', 'detail', 'sidebar', 'about', 'profile', 'action']):
            continue
        for a in section.find_all('a', href=True):
            href = a.get('href', '')
            if _is_external(href):
                return href

    for a in soup.find_all('a', href=True, target='_blank'):
        href = a.get('href', '')
        if _is_external(href):
            return href

    return ''


EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')

# Phrases that signal we've entered the reviews / boilerplate section
_REVIEW_SIGNALS = re.compile(
    r'(verified patient|write a review|all reviews|rating|trustpilot'
    r'|cookie|privacy policy|terms|follow us|newsletter|©)',
    re.IGNORECASE
)


def _extract_about(html: str) -> str:
    """
    Extract the clinic's about/description text from the rendered profile page.
    Doctify shows 3-6 descriptive <p> paragraphs before the reviews section.
    """
    soup = BeautifulSoup(html, 'lxml')
    paragraphs = []

    for p in soup.find_all('p'):
        text = p.get_text(separator=' ', strip=True)
        if len(text) < 60:
            continue
        if _REVIEW_SIGNALS.search(text):
            break
        # Skip cookie/consent text
        if any(k in text.lower() for k in ['cookie', 'gdpr', 'we value your privacy']):
            continue
        paragraphs.append(text)
        if len(paragraphs) >= 6:
            break

    return '\n\n'.join(paragraphs)


def _extract_specialist_count(html: str):
    """
    Try to extract the number of practitioners from the profile page.
    Returns an int or None.
    """
    soup = BeautifulSoup(html, 'lxml')
    text = soup.get_text(separator=' ', strip=True)

    patterns = [
        r'(\d+)\s+specialist',
        r'(\d+)\s+consultant',
        r'(\d+)\s+practitioner',
        r'(\d+)\s+doctor',
        r'team\s+of\s+(\d+)',
        r'(\d+)\s+clinician',
        r'(\d+)\s+surgeon',
        r'(\d+)\s+physician',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 200:
                return val
    return None


def _contact_from_next_data(html: str) -> dict:
    """Extract website, email, and phone from the Next.js __NEXT_DATA__ blob."""
    result = {'website_url': '', 'contact_email': '', 'phone': ''}
    soup = BeautifulSoup(html, 'lxml')
    script = soup.find('script', id='__NEXT_DATA__')
    if not script or not script.string:
        return result
    raw = script.string
    try:
        # Website URL
        for field in ['"websiteUrl"', '"website"', '"externalUrl"', '"practiceWebsite"', '"siteUrl"']:
            idx = raw.find(field)
            while idx != -1:
                snippet = raw[idx:idx + 300]
                m = re.search(r':\s*"(https?://[^"]{4,})"', snippet)
                if m and 'doctify' not in m.group(1):
                    result['website_url'] = m.group(1)
                    break
                idx = raw.find(field, idx + 1)
            if result['website_url']:
                break

        # Email — must pass regex validation to avoid false positives like "08:00"
        for field in ['"email"', '"contactEmail"', '"enquiryEmail"', '"practiceEmail"']:
            idx = raw.find(field)
            while idx != -1:
                snippet = raw[idx:idx + 150]
                m = re.search(r':\s*"([^"]+)"', snippet)
                if m and EMAIL_RE.match(m.group(1)) and 'doctify' not in m.group(1):
                    result['contact_email'] = m.group(1)
                    break
                idx = raw.find(field, idx + 1)
            if result['contact_email']:
                break

        # Phone
        for field in ['"phone"', '"telephone"', '"phoneNumber"', '"contactPhone"']:
            idx = raw.find(field)
            while idx != -1:
                snippet = raw[idx:idx + 100]
                m = re.search(r':\s*"([+0-9 \-\(\)]{7,})"', snippet)
                if m:
                    result['phone'] = m.group(1).strip()
                    break
                idx = raw.find(field, idx + 1)
            if result['phone']:
                break
    except Exception:
        pass
    return result
