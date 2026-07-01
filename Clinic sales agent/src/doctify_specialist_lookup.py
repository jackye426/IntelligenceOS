"""
Doctify specialist profile email lookup.

For a given clinic Doctify URL and CQC person name:
  1. Load the clinic's Doctify practice page to find specialist profile links.
  2. Match the CQC person name against the specialists listed.
  3. Load the specialist's Doctify profile and extract emails from __NEXT_DATA__.
  4. Prefer the email associated with the specific clinic; fall back to any email.
"""

import asyncio
import json
import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Browser

from utils import log


_TITLES = {'mr', 'mrs', 'ms', 'miss', 'dr', 'prof', 'professor', 'sir', 'dame'}

_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/120.0.0.0 Safari/537.36'
)


def _strip_title(name: str) -> str:
    parts = name.strip().split()
    while parts and parts[0].lower().rstrip('.') in _TITLES:
        parts = parts[1:]
    return ' '.join(parts).lower()


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _strip_title(a), _strip_title(b)).ratio()


def _extract_specialist_slugs(html: str) -> list[str]:
    """Pull /uk/specialist/[slug] hrefs from a rendered page."""
    slugs = re.findall(r'/uk/specialist/([a-z0-9][a-z0-9\-]+)', html)
    return list(dict.fromkeys(slugs))  # dedupe, preserve order


def _extract_specialist_data(html: str) -> dict:
    """Parse __NEXT_DATA__ from a specialist profile page."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    nd = soup.find('script', id='__NEXT_DATA__')
    if not nd or not nd.string:
        return {}
    try:
        data = json.loads(nd.string)
        return data.get('props', {}).get('pageProps', {}).get('specialist', {})
    except Exception:
        return {}


def _best_email(specialist: dict, clinic_doctify_url: str) -> str:
    """
    Pick the most relevant email for the target clinic.
    Preference order:
      1. Email whose practice URL/name matches the clinic Doctify URL.
      2. Email from a practice with hasEmails=True.
      3. Any non-generic email from specialist.emails.
    """
    _GENERIC_LOCAL = {'info', 'contact', 'admin', 'hello', 'enquiries',
                      'enquiry', 'reception', 'appointments', 'support',
                      'bookings', 'referrals'}
    _BAD_DOMAINS = {'patientbilling.co.uk', 'nhs.net', 'nhs.uk',
                    'hje.org.uk', 'doctify.com', 'doctify.com.au'}

    def _ok(e: str) -> bool:
        if not e or '@' not in e:
            return False
        return e.split('@')[-1].lower() not in _BAD_DOMAINS

    def _is_generic(e: str) -> bool:
        return e.split('@')[0].lower() in _GENERIC_LOCAL

    clinic_slug = urlparse(clinic_doctify_url).path.rstrip('/').split('/')[-1].lower()
    practices = specialist.get('practices', [])

    # Collect all valid emails from every practice
    clinic_email = ''      # email for the specific target clinic
    other_emails = []      # emails from other practices

    for practice in practices:
        p_slug = str(practice.get('slug') or practice.get('urlSlug') or '').lower()
        p_name = practice.get('name') or ''
        if isinstance(p_name, dict):
            p_name = p_name.get('en', '')
        p_name = str(p_name).lower()

        is_target = clinic_slug and (
            clinic_slug in p_slug or p_slug in clinic_slug or clinic_slug in p_name
        )

        for c in practice.get('ContactDetails', []):
            e = (c.get('email') or '').strip()
            if not _ok(e):
                continue
            if is_target and not clinic_email:
                clinic_email = e
            elif not is_target:
                other_emails.append(e)

    # Also include specialist.emails top-level (often has personal/secretary emails)
    all_emails = [e for e in (specialist.get('emails') or []) if _ok(e)]

    # Preference order:
    #   1. Non-generic email from the target clinic practice
    #   2. Non-generic email from any practice (secretary@, admin@, pa@, personal domain)
    #   3. Non-generic email from specialist.emails
    #   4. Clinic email (even if generic)
    #   5. First available email

    candidates = []
    if clinic_email and not _is_generic(clinic_email):
        candidates.append(clinic_email)
    for e in (other_emails + all_emails):
        if not _is_generic(e) and e not in candidates:
            candidates.append(e)
    if clinic_email and clinic_email not in candidates:
        candidates.append(clinic_email)
    for e in (other_emails + all_emails):
        if e not in candidates:
            candidates.append(e)

    return candidates[0] if candidates else ''


async def _lookup_one(browser: Browser, clinic_url: str, cqc_name: str) -> dict:
    """Core lookup: returns {email, specialist_name, doctify_slug, source}."""
    result = {'email': '', 'specialist_name': '', 'doctify_slug': '', 'source': '', 'match_score': 0.0}

    ctx = await browser.new_context(user_agent=_UA, viewport={'width': 1280, 'height': 800})
    page = await ctx.new_page()

    try:
        # Step 1: load clinic page and extract specialist slugs
        await page.goto(clinic_url, wait_until='networkidle', timeout=25000)
        await asyncio.sleep(1.5)
        html = await page.content()
        slugs = _extract_specialist_slugs(html)

        if not slugs:
            log(f"    Doctify: no specialist links on {clinic_url}")
            return result

        log(f"    Doctify: {len(slugs)} specialists on clinic page")

        # Step 2: match by name similarity
        best_slug = None
        best_score = 0.0

        # Try to get names from the page before loading each profile
        # (slugs often encode the name, e.g. mr-dimitrios-mavrelos)
        for slug in slugs:
            slug_name = slug.replace('-', ' ')
            score = _name_similarity(cqc_name, slug_name)
            if score > best_score:
                best_score = score
                best_slug = slug

        if best_score < 0.55:
            log(f"    Doctify: no slug match above threshold for '{cqc_name}' (best={best_score:.2f})")
            return result

        result['match_score'] = round(best_score, 2)
        log(f"    Doctify: best slug match '{best_slug}' (score {best_score:.2f})")

        # Step 3: load specialist profile
        specialist_url = f"https://www.doctify.com/uk/specialist/{best_slug}"
        await page.goto(specialist_url, wait_until='networkidle', timeout=25000)
        await asyncio.sleep(1.5)
        html = await page.content()

        specialist = _extract_specialist_data(html)
        if not specialist:
            log(f"    Doctify: could not parse specialist data from {specialist_url}")
            return result

        full_name = specialist.get('fullName') or specialist.get('name') or ''
        if isinstance(full_name, dict):
            full_name = full_name.get('en', '')

        email = _best_email(specialist, clinic_url)
        if email:
            log(f"    Doctify: found email '{email}' for '{full_name}'")
            result['email'] = email
            result['specialist_name'] = full_name
            result['doctify_slug'] = best_slug
            result['source'] = 'doctify_profile'

    except Exception as e:
        log(f"    Doctify lookup error: {e}")
    finally:
        await ctx.close()

    return result


async def lookup_specialist_email_async(clinic_doctify_url: str, cqc_name: str,
                                        browser=None) -> dict:
    """
    Async entry point.
    Pass an existing `browser` to reuse it (faster in batch runs).
    If omitted, a new browser is launched and closed automatically.
    """
    if browser is not None:
        return await _lookup_one(browser, clinic_doctify_url, cqc_name)

    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        result = await _lookup_one(b, clinic_doctify_url, cqc_name)
        await b.close()
    return result


def lookup_specialist_email(clinic_doctify_url: str, cqc_name: str) -> dict:
    """Sync wrapper (single lookup, creates its own browser)."""
    return asyncio.run(lookup_specialist_email_async(clinic_doctify_url, cqc_name))
