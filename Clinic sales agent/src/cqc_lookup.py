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


_WEB_COL = "Service's website (if available)"
_SKIP_WEB_HOSTS = {
    "doctify.com",
    "hcahealthcare.co.uk",
    "nhs.uk",
    "google.com",
    "facebook.com",
    "instagram.com",
}


def _website_domain(url: str) -> str:
    """Normalise a clinic website to a bare hostname (no www)."""
    if not url or not str(url).strip():
        return ""
    u = str(url).strip()
    if not u.startswith("http"):
        u = "https://" + u
    # Avoid importing urllib for the hot path shape used elsewhere in the agent.
    m = re.match(r"https?://([^/?#]+)", u, flags=re.I)
    if not m:
        return ""
    host = m.group(1).lower()
    if host.startswith("www."):
        host = host[4:]
    if not host or host in _SKIP_WEB_HOSTS:
        return ""
    return host


def _load_directory():
    """Load (and if needed, download) the CQC directory as a DataFrame."""
    import pandas as pd
    if _needs_refresh(_DIR_PATH):
        _download_directory(_DIR_PATH)
    df = pd.read_csv(_DIR_PATH, encoding='latin-1', skiprows=4, dtype=str)
    df = df.fillna('')
    df['_name_lower'] = df['Name'].str.lower().str.strip()
    df['_web_domain'] = df[_WEB_COL].map(_website_domain)
    return df


_DIR_CACHE = None  # module-level cache so we only load once per process
_WEB_INDEX = None  # domain -> list[row dict]


def _get_dir():
    global _DIR_CACHE, _WEB_INDEX
    if _DIR_CACHE is None:
        _DIR_CACHE = _load_directory()
        _WEB_INDEX = None
    return _DIR_CACHE


def _get_web_index() -> dict:
    """domain -> list of directory row dicts (built once per process)."""
    global _WEB_INDEX
    df = _get_dir()
    if _WEB_INDEX is None:
        idx: dict[str, list] = {}
        for _, row in df[df["_web_domain"] != ""].iterrows():
            idx.setdefault(row["_web_domain"], []).append(row.to_dict())
        _WEB_INDEX = idx
    return _WEB_INDEX


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


def _name_pool(df, base_name: str):
    """Narrow the directory by the longest core token before scoring."""
    words = sorted(_core_words(base_name), key=len, reverse=True)
    if not words:
        return df.iloc[0:0]
    token = words[0]
    narrowed = df[df["_name_lower"].str.contains(re.escape(token), regex=True, na=False)]
    if narrowed.empty:
        return df.iloc[0:0]
    if len(narrowed) > 5000:
        return narrowed.head(5000)
    return narrowed


def _find_by_website(website: str) -> dict | None:
    """Exact hostname match against CQC directory websites."""
    dom = _website_domain(website)
    if not dom:
        return None
    idx = _get_web_index()
    hits = idx.get(dom) or []
    if not hits:
        # try registrable parent (e.g. uk.example.com -> example.com) when 3+ labels
        parts = dom.split(".")
        if len(parts) > 2:
            parent = ".".join(parts[-2:])
            hits = idx.get(parent) or []
    if not hits:
        return None
    return hits[0]


def _find_in_directory(
    clinic_name: str,
    location_str: str = "",
    website: str = "",
) -> tuple[dict | None, str]:
    """
    Match a clinic against the CQC directory.

    Returns (row, method) where method is one of:
      geo | name_only | website | name_website | ""
    """
    df = _get_dir()
    base_name = _strip_branch(clinic_name)
    base_lower = base_name.lower().strip()

    postcode = _extract_postcode(location_str).replace(" ", "").upper()

    def _name_match(pool, threshold: float = 0.6, *, global_strict: bool = False):
        """Try name-based strategies within a pool. Returns best row dict or None."""
        # a. Exact match on full or branch-stripped name
        for candidate in [clinic_name, base_name]:
            exact = pool[pool["_name_lower"] == candidate.lower().strip()]
            if not exact.empty:
                return exact.iloc[0].to_dict()

        # b. CQC name contains our base name (avoid ultra-short bases)
        if len(base_lower) >= 6:
            contains = pool[
                pool["_name_lower"].str.contains(re.escape(base_lower), regex=True, na=False)
            ]
            if not contains.empty:
                return contains.iloc[contains["Name"].str.len().argmin()].to_dict()

        # c. Word overlap
        if pool.empty:
            return None
        scores = pool["_name_lower"].apply(lambda n: _word_overlap(base_name, n))
        best_score = float(scores.max()) if len(scores) else 0.0
        if best_score < threshold:
            return None
        top = pool[scores == best_score]
        wa = _core_words(base_name)
        best_row = top.iloc[
            top["_name_lower"].apply(lambda n: len(wa & _core_words(n))).argmax()
        ]
        if global_strict:
            # Reject single-token collisions (e.g. Queen's Clinic -> Queen's Hospital).
            shared = wa & _core_words(best_row["Name"])
            if len(shared) < 2:
                return None
        return best_row.to_dict()

    # Strategy 1: exact postcode — threshold lowered because location is already pinpointed
    if postcode:
        pc_pool = df[df["Postcode"].str.replace(" ", "", regex=False).str.upper() == postcode]
        if not pc_pool.empty:
            row = _name_match(pc_pool, threshold=0.45)
            if row:
                return row, "geo"

    # Strategy 2: postcode prefix ("W1G" then "W1") — stricter threshold
    if postcode:
        for prefix, thresh in ((postcode[:3], 0.6), (postcode[:2], 0.7)):
            prefix_pool = df[
                df["Postcode"]
                .str.replace(" ", "", regex=False)
                .str.upper()
                .str.startswith(prefix)
            ]
            if not prefix_pool.empty:
                row = _name_match(prefix_pool, threshold=thresh)
                if row:
                    return row, "geo"

    # Strategy 3: website hostname (independent of geo)
    web_hit = _find_by_website(website) if website else None

    # Strategy 4: name-only across directory (also when postcode was present but failed)
    name_pool = _name_pool(df, base_name)
    name_hit = _name_match(name_pool, threshold=0.75, global_strict=True)

    if web_hit and name_hit:
        web_id = (web_hit.get("CQC Location ID (for office use only)") or "").strip()
        name_id = (name_hit.get("CQC Location ID (for office use only)") or "").strip()
        if web_id and name_id and web_id == name_id:
            return name_hit, "name_website"
        # Prefer exact/branch name over a conflicting website hit
        name_l = (name_hit.get("Name") or "").lower().strip()
        if name_l in {clinic_name.lower().strip(), base_lower}:
            return name_hit, "name_only"
        return web_hit, "website"

    if web_hit:
        return web_hit, "website"
    if name_hit:
        return name_hit, "name_only"

    return None, ""


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

def lookup_cqc(clinic_name: str, location: str = "", website: str = "") -> dict:
    """
    Find the CQC contacts for a clinic.

    Args:
        clinic_name: Name as scraped from Doctify.
        location:    Full Doctify location string (e.g. "0.21 miles | 10 Harley Street, London, W1G 9PF").
        website:     Clinic website URL from Doctify (optional; used for hostname match).

    Returns dict with:
        cqc_location_id          — CQC location ID
        cqc_registered_manager   — Person legally responsible for day-to-day operations
        cqc_nominated_individual — Person responsible for supervising regulated activities
                                   (usually the lead clinician / owner who makes decisions)
        cqc_match_confidence     — "exact" | "fuzzy" | "name_only" | "website" | "name_website" | ""
    """
    result = {
        "cqc_location_id": "",
        "cqc_registered_manager": "",
        "cqc_nominated_individual": "",
        "cqc_match_confidence": "",
    }

    if not clinic_name or not clinic_name.strip():
        return result

    row, method = _find_in_directory(clinic_name, location, website=website)
    if not row:
        log(f"  CQC: '{clinic_name}' not found in directory")
        return result

    location_url = row.get("Location URL", "").strip()
    location_id = row.get("CQC Location ID (for office use only)", "").strip()
    matched_name = row.get("Name", "")

    result["cqc_location_id"] = location_id
    is_exact = matched_name.lower().strip() == clinic_name.lower().strip()
    if method in {"name_only", "website", "name_website"}:
        result["cqc_match_confidence"] = method
    else:
        result["cqc_match_confidence"] = "exact" if is_exact else "fuzzy"

    if not location_url:
        log(f"  CQC: found '{matched_name}' but no location URL")
        return result

    time.sleep(_PAGE_DELAY)
    roles = _scrape_cqc_roles(location_url)
    result["cqc_registered_manager"] = roles["registered_manager"]
    result["cqc_nominated_individual"] = roles["nominated_individual"]

    parts = []
    if roles["nominated_individual"]:
        parts.append(f"responsible: {roles['nominated_individual']}")
    if roles["registered_manager"]:
        parts.append(f"manager: {roles['registered_manager']}")

    if parts:
        log(
            f"  CQC ({result['cqc_match_confidence']} -> '{matched_name}'): "
            f"{' | '.join(parts)}"
        )
    else:
        log(f"  CQC: found '{matched_name}' but no contacts listed on page")

    return result
