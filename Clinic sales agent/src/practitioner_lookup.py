"""
Practitioner email lookup via Supabase integrated_practitioners table.

Matches a CQC person name (e.g. "Mrs Chloe Margaret Worthy Darnley") against
the practitioners database and returns their email address.
"""

import re
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

_DB_URL = os.getenv('SUPABASE_DATABASE_POOLER_URL') or os.getenv('supabase_database_url', '')

_TITLES = {'mr', 'mrs', 'ms', 'miss', 'dr', 'prof', 'professor', 'sir', 'dame', 'rev'}

# Domains that are clearly billing services, not the clinic itself
_BAD_DOMAINS = {
    'patientbilling.co.uk', 'ccf.org', 'nhs.net', 'nhs.uk',
    'hje.org.uk',  # private billing aggregator
}

_conn = None


def _get_conn():
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(_DB_URL, connect_timeout=10)
        _conn.autocommit = True
    return _conn


def _parse_name(full_name: str) -> tuple[str, str]:
    """
    Parse a CQC full name into (first_name, last_name).
    Strips honorifics and handles middle names.
    Examples:
      "Mrs Chloe Margaret Worthy Darnley" -> ("Chloe", "Darnley")
      "Mr Narendra Vinayak Pisal"         -> ("Narendra", "Pisal")
      "Shirin Khanjani"                   -> ("Shirin", "Khanjani")
    """
    parts = full_name.strip().split()
    # Drop leading title(s)
    while parts and parts[0].lower().rstrip('.') in _TITLES:
        parts = parts[1:]
    if not parts:
        return '', ''
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], parts[-1]


def _clinic_domain(website_url: str) -> str:
    """Extract bare domain from a website URL."""
    url = website_url.lower().strip().lstrip('https://').lstrip('http://').lstrip('www.')
    return url.split('/')[0].split('?')[0]


def lookup_practitioner(cqc_name: str, website_url: str = '') -> dict:
    """
    Find a practitioner's email by matching their CQC name against the database.

    Matching strategy (in order):
      1. Exact full name match on `name` column
      2. first_name ILIKE + last_name ILIKE
      3. last_name only (if unique result)

    Returns dict with:
        decision_maker_email        — best email found (blank if not found)
        decision_maker_name_matched — exact name from the database
        decision_maker_email_source — 'exact_name' | 'first_last' | 'last_only' | ''
    """
    result = {
        'decision_maker_email': '',
        'decision_maker_name_matched': '',
        'decision_maker_email_source': '',
        'decision_maker_email_confidence': '',
        'decision_maker_email_verified': '',
    }

    if not cqc_name or not cqc_name.strip():
        return result

    first, last = _parse_name(cqc_name)
    if not last:
        return result

    _SELECT = (
        "SELECT name, email, emails, email_confidence, email_manually_verified "
        "FROM integrated_practitioners "
    )

    try:
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Strategy 1: exact full name
        cur.execute(
            _SELECT + "WHERE LOWER(name) = LOWER(%s) "
            "AND (email IS NOT NULL OR emails IS NOT NULL) LIMIT 3",
            (cqc_name.strip(),)
        )
        rows = cur.fetchall()

        # Strategy 2: first_name + last_name
        if not rows and first:
            cur.execute(
                _SELECT + "WHERE LOWER(first_name) ILIKE LOWER(%s) "
                "AND LOWER(last_name) = LOWER(%s) "
                "AND (email IS NOT NULL OR emails IS NOT NULL) LIMIT 3",
                (first + '%', last)
            )
            rows = cur.fetchall()

        # Strategy 3: last name only — only if unique result
        if not rows:
            cur.execute(
                _SELECT + "WHERE LOWER(last_name) = LOWER(%s) "
                "AND (email IS NOT NULL OR emails IS NOT NULL) LIMIT 3",
                (last,)
            )
            rows = cur.fetchall()
            if len(rows) != 1:
                rows = []  # ambiguous — skip

        if not rows:
            return result

        # If multiple matches, prefer manually verified or highest confidence
        row = sorted(
            rows,
            key=lambda r: (bool(r.get('email_manually_verified')), r.get('email_confidence') or 0),
            reverse=True
        )[0]

        matched_name = row.get('name') or cqc_name

        # Build a ranked list of all available emails, filtering known bad domains
        all_emails = []
        for e in ([row.get('email')] if row.get('email') else []):
            all_emails.append(e)
        emails_arr = row.get('emails') or []
        if isinstance(emails_arr, list):
            all_emails.extend(emails_arr)

        clinic_dom = _clinic_domain(website_url) if website_url else ''

        def _domain(e):
            return e.split('@')[-1].lower() if '@' in e else ''

        def _is_generic_local(e):
            local = e.split('@')[0].lower()
            return local in {'info', 'contact', 'admin', 'hello', 'enquiries',
                             'enquiry', 'reception', 'appointments', 'support',
                             'bookings', 'referrals', 'secretary'}

        # Rank: clinic-domain match > not-bad-domain > others
        seen = set()
        ranked = []
        for e in all_emails:
            if not e or '@' not in e or e in seen:
                continue
            seen.add(e)
            dom = _domain(e)
            is_clinic = bool(clinic_dom and clinic_dom in dom)
            is_bad = dom in _BAD_DOMAINS
            is_generic = _is_generic_local(e)
            # Lower tuple = better rank
            ranked.append((not is_clinic, is_bad, is_generic, e))
        ranked.sort(key=lambda x: x[:3])

        email = ranked[0][3] if ranked else ''

        if not email:
            return result

        source = 'exact_name' if matched_name.lower().strip() == cqc_name.lower().strip() else 'first_last'
        result['decision_maker_email'] = email
        result['decision_maker_name_matched'] = matched_name
        result['decision_maker_email_source'] = source
        result['decision_maker_email_confidence'] = str(row.get('email_confidence') or '')
        result['decision_maker_email_verified'] = str(row.get('email_manually_verified') or '')
        return result

    except Exception as e:
        from utils import log
        log(f"  Practitioner DB error: {e}")
        return result
