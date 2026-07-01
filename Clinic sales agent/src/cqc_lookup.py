"""
CQC (Care Quality Commission) lookup — finds the Registered Manager for a clinic.

Approach:
  1. Load the CQC public directory CSV (downloaded once, refreshed if >7 days old).
  2. Fuzzy-match the clinic name to find its CQC location URL.
  3. Scrape that location page for the Registered Manager name.

The Registered Manager is the person legally named as responsible for day-to-day
operations. Every regulated private clinic in England must disclose this publicly.
"""

import os
import re
import time
import datetime
import requests
from bs4 import BeautifulSoup

from utils import log

_TRANSPARENCY_URL = "https://www.cqc.org.uk/about-us/transparency/using-cqc-data"
_DIR_PATH = os.path.join(os.path.dirname(__file__), '..', 'output', 'cqc_directory.csv')
_DIR_MAX_AGE_DAYS = 7

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "Accept": "text/html,application/json,*/*",
})
_PAGE_DELAY = 1.0  # seconds between CQC page scrapes


# ---------------------------------------------------------------------------
# Directory management
# ---------------------------------------------------------------------------

def _find_csv_url() -> str:
    """Scrape the CQC transparency page to get the current directory CSV URL."""
    r = _SESSION.get(_TRANSPARENCY_URL, timeout=20)
    r.raise_for_status()
    match = re.search(r'https://www\.cqc\.org\.uk/sites/default/files/[^"\']*CQC_directory\.csv', r.text)
    if not match:
        raise RuntimeError("Could not find CQC directory CSV URL on transparency page")
    return match.group(0)


def _download_directory(dest: str):
    log("  CQC: downloading directory CSV...")
    url = _find_csv_url()
    r = _SESSION.get(url, timeout=120, stream=True)
    r.raise_for_status()
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    with open(dest, 'wb') as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)
    log(f"  CQC: directory saved ({os.path.getsize(dest) / 1024 / 1024:.1f} MB)")


def _needs_refresh(path: str) -> bool:
    if not os.path.exists(path):
        return True
    age = datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(path))
    return age.days >= _DIR_MAX_AGE_DAYS


def _load_directory():
    """Load (and if needed, download) the CQC directory as a DataFrame."""
    import pandas as pd
    if _needs_refresh(_DIR_PATH):
        _download_directory(_DIR_PATH)
    df = pd.read_csv(_DIR_PATH, encoding='latin-1', skiprows=4, dtype=str)
    df = df.fillna('')
    df['_name_lower'] = df['Name'].str.lower().str.strip()
    return df


_DIR_CACHE = None  # module-level cache so we only load once per process


def _get_dir():
    global _DIR_CACHE
    if _DIR_CACHE is None:
        _DIR_CACHE = _load_directory()
    return _DIR_CACHE


# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------

_GENERIC_WORDS = {
    'clinic', 'centre', 'center', 'practice', 'surgery', 'medical',
    'health', 'healthcare', 'limited', 'ltd', 'london', 'harley street',
    'consulting', 'consultants', 'services', 'group', 'the', 'at', 'and',
}


def _strip_branch(name: str) -> str:
    """Remove branch/location suffix (e.g. '- Harley Street', '| Moorgate')."""
    for sep in [' - ', ' | ', ' @ ']:
        if sep in name:
            return name.split(sep)[0].strip()
    return name.strip()


def _core_words(name: str) -> set:
    """Return significant lowercase words from a clinic name."""
    words = re.findall(r"[a-z0-9']+", name.lower())
    return {w for w in words if w not in _GENERIC_WORDS and len(w) > 2}


def _word_overlap(a: str, b: str) -> float:
    """Fraction of core words in `a` that appear in `b`."""
    wa = _core_words(a)
    if not wa:
        return 0.0
    wb = _core_words(b)
    return len(wa & wb) / len(wa)


def _extract_postcode(location_str: str) -> str:
    """Pull a UK postcode out of a Doctify location string."""
    m = re.search(r'\b([A-Z]{1,2}[0-9][0-9A-Z]?\s*[0-9][A-Z]{2})\b', location_str.upper())
    return m.group(1).strip() if m else ''


def _extract_street(location_str: str) -> str:
    """Pull the street portion (e.g. '10 Harley Street') from a Doctify location string."""
    # Format: "0.21 miles | 10 Harley Street, London, United Kingdom, W1G 9PF"
    parts = location_str.split('|')
    if len(parts) > 1:
        addr = parts[-1].strip()
        # Take everything before the first comma (the street)
        return addr.split(',')[0].strip().lower()
    return ''


def _find_in_directory(clinic_name: str, location_str: str = '') -> dict | None:
    """
    Match a clinic name against the CQC directory using name + postcode + address.
    Returns the best matching row as a dict, or None.
    """
    df = _get_dir()
    base_name = _strip_branch(clinic_name)
    base_lower = base_name.lower().strip()

    postcode = _extract_postcode(location_str).replace(' ', '').upper()
    street = _extract_street(location_str)

    def _name_match(pool, threshold: float = 0.6):
        """Try name-based strategies within a pool. Returns best row dict or None."""
        # a. Exact match on full or branch-stripped name
        for candidate in [clinic_name, base_name]:
            exact = pool[pool['_name_lower'] == candidate.lower().strip()]
            if not exact.empty:
                return exact.iloc[0].to_dict()

        # b. CQC name contains our base name
        if len(base_lower) >= 4:
            contains = pool[pool['_name_lower'].str.contains(re.escape(base_lower), regex=True, na=False)]
            if not contains.empty:
                return contains.iloc[contains['Name'].str.len().argmin()].to_dict()

        # c. Word overlap — pick highest scorer above threshold; break ties by most shared words
        scores = pool['_name_lower'].apply(lambda n: _word_overlap(base_name, n))
        best_score = scores.max()
        if best_score >= threshold:
            top = pool[scores == best_score]
            # Prefer the record that shares the most absolute words with our name
            wa = _core_words(base_name)
            best_row = top.iloc[
                top['_name_lower'].apply(lambda n: len(wa & _core_words(n))).argmax()
            ]
            return best_row.to_dict()

        return None

    # Strategy 1: exact postcode — threshold lowered because location is already pinpointed
    if postcode:
        pc_pool = df[df['Postcode'].str.replace(' ', '', regex=False).str.upper() == postcode]
        if not pc_pool.empty:
            row = _name_match(pc_pool, threshold=0.45)
            if row:
                return row
            # Name didn't match any clinic at that postcode — clinic is likely not CQC-registered

    # Strategy 2: postcode prefix ("W1G" then "W1") — stricter threshold
    if postcode:
        for prefix, thresh in ((postcode[:3], 0.6), (postcode[:2], 0.7)):
            prefix_pool = df[df['Postcode'].str.replace(' ', '', regex=False).str.upper().str.startswith(prefix)]
            if not prefix_pool.empty:
                row = _name_match(prefix_pool, threshold=thresh)
                if row:
                    return row

    # Strategy 3: name-only, whole directory — only when no postcode available
    if not postcode:
        row = _name_match(df, threshold=0.75)
        return row

    return None


# ---------------------------------------------------------------------------
# Page scraping
# ---------------------------------------------------------------------------

def _scrape_cqc_roles(location_url: str) -> dict:
    """
    Scrape a CQC location page and return both key contacts.

    Returns dict with:
        registered_manager   — person legally responsible for day-to-day operations
        nominated_individual — person responsible for supervising regulated activities
                               (usually the lead clinician / owner who makes decisions)
    """
    out = {'registered_manager': '', 'nominated_individual': ''}
    try:
        r = _SESSION.get(location_url, timeout=15)
        r.raise_for_status()
    except Exception as e:
        log(f"  CQC: page fetch failed ({e})")
        return out

    soup = BeautifulSoup(r.text, 'html.parser')

    _ROLE_LABELS = ['Nominated Individual', 'Registered Manager']

    for role_tag in soup.find_all('p', class_='two-col__title--who-runs-service'):
        tag_text = role_tag.get_text(strip=True)

        matched_label = None
        for label in _ROLE_LABELS:
            if label in tag_text:
                matched_label = label
                break

        if not matched_label:
            # "responsible for these services" on individual-provider pages
            if 'responsible for' in tag_text.lower() and not out['nominated_individual']:
                name = re.sub(r'responsible for.*', '', tag_text, flags=re.I).strip()
                name = re.sub(r'\s+', ' ', name).strip()
                if name:
                    out['nominated_individual'] = name
            continue

        # Strip the role label to get just the name
        name = tag_text.replace(matched_label, '').strip()
        name = re.sub(r'\s+', ' ', name).strip()
        if not name:
            continue

        if matched_label == 'Registered Manager':
            out['registered_manager'] = name
        else:
            out['nominated_individual'] = name

    return out


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def lookup_cqc(clinic_name: str, location: str = '') -> dict:
    """
    Find the CQC contacts for a clinic.

    Args:
        clinic_name: Name as scraped from Doctify.
        location:    Full Doctify location string (e.g. "0.21 miles | 10 Harley Street, London, W1G 9PF").

    Returns dict with:
        cqc_location_id          — CQC location ID
        cqc_registered_manager   — Person legally responsible for day-to-day operations
        cqc_nominated_individual — Person responsible for supervising regulated activities
                                   (usually the lead clinician / owner who makes decisions)
        cqc_match_confidence     — "exact" | "fuzzy" | ""
    """
    result = {
        'cqc_location_id': '',
        'cqc_registered_manager': '',
        'cqc_nominated_individual': '',
        'cqc_match_confidence': '',
    }

    if not clinic_name or not clinic_name.strip():
        return result

    row = _find_in_directory(clinic_name, location)
    if not row:
        log(f"  CQC: '{clinic_name}' not found in directory")
        return result

    location_url = row.get('Location URL', '').strip()
    location_id = row.get('CQC Location ID (for office use only)', '').strip()
    matched_name = row.get('Name', '')

    result['cqc_location_id'] = location_id
    is_exact = matched_name.lower().strip() == clinic_name.lower().strip()
    result['cqc_match_confidence'] = 'exact' if is_exact else 'fuzzy'

    if not location_url:
        log(f"  CQC: found '{matched_name}' but no location URL")
        return result

    time.sleep(_PAGE_DELAY)
    roles = _scrape_cqc_roles(location_url)
    result['cqc_registered_manager'] = roles['registered_manager']
    result['cqc_nominated_individual'] = roles['nominated_individual']

    parts = []
    if roles['nominated_individual']:
        parts.append(f"responsible: {roles['nominated_individual']}")
    if roles['registered_manager']:
        parts.append(f"manager: {roles['registered_manager']}")

    if parts:
        log(f"  CQC ({result['cqc_match_confidence']} -> '{matched_name}'): {' | '.join(parts)}")
    else:
        log(f"  CQC: found '{matched_name}' but no contacts listed on page")

    return result
