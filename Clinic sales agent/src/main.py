"""
Clinic Sales Pipeline — main entry point.

Usage examples:
  # Scrape 1 page, print results only (no LLM):
  python src/main.py --pages 1 --scrape-only

  # Scrape 3 pages, full pipeline with LLM:
  python src/main.py --pages 3

  # Enrich existing CSV (no re-scrape, no website crawl), test on 5:
  python src/main.py --enrich-only --skip-crawl --max-clinics 5
"""

import argparse
import asyncio
import csv
import os
import sys
import random
import time
from datetime import datetime, timedelta, date

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

from config import OPENROUTER_API_KEY, GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH
from utils import log
from doctify_scraper import scrape_doctify
from website_crawler import crawl_website
from text_cleaner import clean_and_cap
from llm_enrichment import enrich_clinic, judge_email, clean_clinic_name, EMAIL_TEMPLATE
from csv_writer import write_results, append_result, COLUMNS, _flatten, _safe_save
from cqc_lookup import lookup_cqc

DEFAULT_OUTPUT = os.path.join(
    os.path.dirname(__file__), '..', 'output', 'clinic_sales_results.csv'
)
INPUT_URLS_CSV = os.path.join(os.path.dirname(__file__), '..', 'input_urls.csv')

# Hard pre-filter: clinic name contains these -> skip before LLM
_HOSPITAL_SIGNALS = [
    # NHS / trust
    'hospital', 'nhs trust', 'nhs foundation', 'foundation trust',
    'university college hospital', "king's college hospital", 'kings college hospital',
    'st thomas', 'royal free', 'imperial college', 'moorfields',
    # Major private hospital groups (purchasing decision not held by the clinic)
    'hca healthcare', 'hca uk', 'lister hospital',
    'london bridge hospital', 'the wellington hospital', 'portland hospital',
    'cromwell hospital', 'princess grace hospital',
    'spire health', 'spire healthcare',
    'ramsay health', 'ramsay healthcare',
    'bmi healthcare', 'bmi health',
    'nuffield health',
    'bupa health',
    'circle health',
    'aspen healthcare',
]

# Specialties that on their own indicate a low-value-for-us practice
_LOW_VALUE_SPECIALTIES = {
    'physiotherapy', 'physiotherapist', 'acupuncture', 'acupuncturist',
    'osteopathy', 'osteopath', 'chiropractic', 'chiropractor',
    'homeopathy', 'homeopath', 'podiatry', 'podiatrist',
    'reflexology', 'aromatherapy', 'naturopathy', 'herbalist',
    'massage therapy', 'sports therapy',
}

# Any of these in specialty tags = keep regardless of low-value tags also present
_HIGH_VALUE_SPECIALTIES = {
    'gynaecol', 'gynecol', 'fertility', 'ivf', 'endometriosis',
    'obstetric', 'reproductive', 'menopause', 'pelvic', "women's health",
    'womens health', 'urogyn', 'hysteroscop', 'laparoscop',
    'urolog', 'orthopaed', 'orthoped', 'ophthalm', 'dermatol',
    "men's health", 'mens health', 'longevity', 'andrology', 'imaging',
    'radiology', 'diagnostics',
}

# Code-based pre-scoring: high-value surgical / complex procedure keywords
_CS_HVP = [
    # Women's health / fertility
    'ivf', 'in vitro', 'egg freezing', 'endometriosis', 'fertility treatment',
    'fertility preservation', 'reproductive medicine', 'embryo', 'surrogacy',
    'ovarian stimulation', 'sperm donation', 'egg donation', 'intracytoplasmic',
    'egg_freezing',
    # Orthopaedic surgery
    'joint replacement', 'knee replacement', 'hip replacement', 'arthroscop',
    'spine surgery', 'spinal surgery',
    # Ophthalmology
    'laser eye', 'cataract surgery', 'refractive surgery', 'lasik', 'femtosecond',
    'retinal surgery',
    # Urology surgical
    'prostate surgery', 'prostatectomy', 'lithotripsy', 'kidney stone surgery',
    # Dermatology clinical
    'mohs surgery', 'skin cancer surgery',
]
# Code-based pre-scoring: specialist / relevant-specialty keywords
_CS_GYNAE = [
    # Women's health
    'gynaecol', 'gynecol', 'obstetric', 'menopause', 'urogyn',
    'hysteroscop', 'laparoscop', 'pcos', 'fibroids', "women's health",
    'womens health', 'pelvic floor', 'colposcop', 'vulvodynia',
    # Urology
    'urolog', 'prostate', 'bladder', 'andrology', 'vasectomy', 'incontinence',
    # Orthopaedics
    'orthopaed', 'orthoped', 'sports injury', 'arthritis',
    # Ophthalmology
    'ophthalm', 'glaucoma', 'macular', 'retina', 'cataract',
    # Dermatology
    'dermatol', 'skin cancer', 'mole removal', 'eczema', 'psoriasis',
    # Men's health / longevity
    "men's health", 'mens health', 'testosterone', 'erectile dysfunction',
    'longevity', 'health optimisation', 'executive health',
]


def _code_score_clinic(clinic: dict) -> int:
    """
    Heuristic score 0-100 from scraped metadata (no LLM).
    Primary signal: specialist count (size / revenue capacity proxy).
    Secondary: surgical keywords and specialty breadth.
    """
    tags = clinic.get('specialty_tags', [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(';') if t.strip()]
    text = ' '.join(tags).lower() + ' ' + clinic.get('doctify_about', '').lower()

    # Hard floor: holistic-only with no clinical signals
    _HOLISTIC = ['homeopath', 'acupunctur', 'reflexolog', 'aromatherapy', 'naturopath', 'herbalist']
    _CLINICAL = ['surgeon', 'consultant', 'specialist', 'doctor', 'physician', 'procedure']
    if any(kw in text for kw in _HOLISTIC) and not any(kw in text for kw in _CLINICAL):
        return 5

    # Primary: specialist count
    try:
        count = int(float(str(clinic.get('specialist_count') or 0)))
    except (ValueError, TypeError):
        count = 0

    if count >= 7:
        base = 65
    elif count >= 4:
        base = 55
    elif count >= 2:
        base = 40
    elif count == 1:
        base = 25
    else:
        base = 20  # unknown — give benefit of doubt

    # +15 if any high-value / surgical procedure is mentioned
    if any(kw in text for kw in _CS_HVP):
        base += 15

    # +10 for multi-specialty breadth (proxy for pathway complexity)
    specialty_hits = sum(1 for kw in _CS_GYNAE if kw in text)
    if specialty_hits >= 3:
        base += 10
    elif specialty_hits >= 1:
        base += 5

    # +10/+5 for high review count — proxy for patient volume and website traffic
    try:
        reviews = int(float(str(clinic.get('review_count') or 0)))
    except (ValueError, TypeError):
        reviews = 0
    if reviews >= 100:
        base += 10
    elif reviews >= 50:
        base += 5

    return min(base, 100)


def read_input_urls(pages_override: int = None) -> list:
    """Read target URLs from input_urls.csv. Returns [{url, pages}, ...]."""
    if not os.path.exists(INPUT_URLS_CSV):
        return []
    df = pd.read_csv(INPUT_URLS_CSV)
    result = []
    for _, row in df.iterrows():
        url = str(row.get('url', '')).strip()
        if not url or url.startswith('#'):
            continue
        pages = pages_override if pages_override is not None else int(row.get('pages', 1))
        result.append({'url': url, 'pages': pages})
    return result


_MIN_ABOUT_CHARS = 80
_MIN_WEBSITE_CHARS = 150


def _has_sufficient_info(clinic: dict) -> bool:
    """True if the Doctify bio has enough content to write a meaningful personalised email."""
    about = clinic.get('doctify_about', '').strip()
    return len(about) >= _MIN_ABOUT_CHARS


def _pre_filter_clinic(clinic: dict) -> str | None:
    """
    Returns a skip-reason string for obvious low-value clinics (saves LLM calls),
    or None to let the clinic through to scoring.
    """
    name = clinic.get('clinic_name', '').lower()

    for signal in _HOSPITAL_SIGNALS:
        if signal in name:
            return f'hospital/NHS: "{signal}"'

    # Only filter on specialties if we actually have them and none are high-value
    tags = clinic.get('specialty_tags', [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(';') if t.strip()]
    if tags:
        tags_lower = [t.lower() for t in tags]
        has_high_value = any(
            any(hv in tag for hv in _HIGH_VALUE_SPECIALTIES)
            for tag in tags_lower
        )
        all_low_value = all(
            any(lv in tag for lv in _LOW_VALUE_SPECIALTIES)
            for tag in tags_lower
        )
        if all_low_value and not has_high_value:
            return f'low-value specialties only: {"; ".join(tags[:3])}'

    return None


def parse_args():
    p = argparse.ArgumentParser(description='Clinic sales pipeline')
    p.add_argument('--start-url', default=None, help='Single Doctify listing URL (overrides input_urls.csv)')
    p.add_argument('--pages', type=int, default=None, help='Override page count for all URLs (default: use input_urls.csv values)')
    p.add_argument('--output', default=DEFAULT_OUTPUT, help='Output CSV path')
    p.add_argument('--max-clinics', type=int, default=None, help='Cap total clinics processed')
    p.add_argument(
        '--scrape-only', action='store_true',
        help='Stop after scraping (skip website crawl and LLM)'
    )
    p.add_argument(
        '--append', action='store_true',
        help='Skip clinics already in the output CSV (fill in missing ones)'
    )
    p.add_argument(
        '--listing-delay', type=float, default=None,
        help='Seconds between listing page loads (default 1.5; use 4-5 to avoid rate limiting)'
    )
    p.add_argument(
        '--enrich-only', action='store_true',
        help='Skip Doctify scraping — run LLM on code_passed rows (or unknown if no code score run)'
    )
    p.add_argument(
        '--code-score-only', action='store_true',
        help='Run code scoring on unknown rows only — marks code_passed / low_score, no LLM'
    )
    p.add_argument(
        '--crawl', action='store_true',
        help='Crawl clinic websites for additional context (off by default — bio only)'
    )
    p.add_argument(
        '--cqc', action='store_true',
        help='Look up each clinic in the CQC registry to find the Registered Manager'
    )
    p.add_argument(
        '--cqc-only', action='store_true',
        help='Run CQC lookup on all rows in the existing CSV that have not been looked up yet'
    )
    p.add_argument(
        '--match-emails', action='store_true',
        help='Match CQC person names against the practitioners DB to find direct email addresses'
    )
    p.add_argument(
        '--doctify-emails', action='store_true',
        help='Scrape Doctify specialist profiles to find direct emails for CQC-matched people'
    )
    p.add_argument(
        '--require-email', action='store_true',
        help='Only process clinics that have a contact email (enrich-only mode)'
    )
    p.add_argument(
        '--sync-sent', action='store_true',
        help='Sync Gmail sent-box status into the CSV (no follow-up drafts created)'
    )
    p.add_argument(
        '--followup', action='store_true',
        help='Sync sent status then create follow-up drafts for eligible clinics'
    )
    p.add_argument(
        '--followup-days', type=int, default=2,
        help='Days since send before a follow-up is drafted (default 2)'
    )
    p.add_argument(
        '--dry-run', action='store_true',
        help='With --followup: check eligibility and print counts without creating drafts'
    )
    p.add_argument(
        '--send-approved', action='store_true',
        help='Send approved auto-send drafts, staggered across working hours (9-12, 14-17)'
    )
    p.add_argument(
        '--send-delay-min', type=int, default=1,
        help='Minimum minutes between sends (default 1)'
    )
    p.add_argument(
        '--send-delay-max', type=int, default=3,
        help='Maximum minutes between sends (default 3)'
    )
    return p.parse_args()


def _setup_gmail():
    if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
        log("Gmail credentials not found — drafts will be skipped.")
        return None
    from gmail_draft import create_draft
    log("Gmail drafts enabled.")
    return create_draft


def _enrich_and_draft(clinic: dict, website_text: str, create_draft_fn):
    if not OPENROUTER_API_KEY:
        clinic.setdefault('status', 'no_llm_key')
        return

    code_score = _code_score_clinic(clinic)
    log(f"  Code score: {code_score}")
    if code_score <= 40:
        clinic['status'] = 'low_score'
        clinic['fit_score'] = code_score
        clinic['filter_reason'] = f'code score {code_score} (below threshold)'
        log(f"  Skipping LLM — code score too low")
        return

    try:
        log("  Running LLM enrichment...")
        enriched = enrich_clinic(clinic, website_text)
        clinic.update(enriched)
        score = enriched.get('fit_score', 0)
        log(f"  Fit score: {score}")
        if score > 60:
            try:
                specialist_count = int(float(str(clinic.get('specialist_count') or 0)))
            except (ValueError, TypeError):
                specialist_count = 0
            if specialist_count >= 20:
                # Large clinic: find decision-maker email manually
                clinic['status'] = 'needs_manual_contact'
                clinic['filter_reason'] = f'{specialist_count} specialists — find decision-maker email manually'
                log(f"  Large clinic ({specialist_count} specialists) — flagged for manual contact")
            elif specialist_count < 10:
                # Small clinic: eligible for auto-send after judge approval
                clinic['status'] = 'drafted'
                clinic['auto_send_eligible'] = 'true'
                log(f"  Small clinic ({specialist_count} specialists) — eligible for auto-send")
            else:
                # Mid-size (10-19): draft for manual review
                clinic['status'] = 'drafted'
                clinic['auto_send_eligible'] = 'false'
                log(f"  Mid-size clinic ({specialist_count} specialists) — draft for manual review")
        else:
            clinic['status'] = 'low_score'
            log(f"  Score <= 60 — skipping email draft")
    except Exception as e:
        log(f"  LLM failed: {e}")
        if clinic.get('status') != 'crawl_failed':
            clinic['status'] = 'llm_failed'
        clinic['error'] = str(e)
        return

    if create_draft_fn and clinic.get('status') in ('drafted', 'needs_manual_contact'):
        email = clinic.get('contact_email', '').strip()
        subject = clinic.get('suggested_subject', '')
        body = clinic.get('suggested_email_body', '')

        if email and subject and body:
            # Judge pass — independent LLM review before drafting
            try:
                log("  Running judge review...")
                verdict = judge_email(
                    clinic_name=clinic.get('clinic_name', ''),
                    salutation_name=clinic.get('salutation_name', ''),
                    ideal_patient_type=clinic.get('ideal_patient_type', ''),
                    email_body=body,
                )
                clinic['judge_approved'] = str(verdict.get('approved', True))
                clinic['judge_reason'] = verdict.get('rejection_reason', '')

                # If judge rewrote ideal_patient_type, rebuild the email
                revised = verdict.get('revised_ideal_patient_type', '').strip()
                if revised:
                    log(f"  Judge revised patient type: {revised}")
                    clinic['ideal_patient_type'] = revised

                    salutation_name = clinic.get('salutation_name') or clean_clinic_name(clinic.get('clinic_name', ''))
                    body = EMAIL_TEMPLATE.format(
                        clinic_name=clinic.get('clinic_name', ''),
                        salutation_name=salutation_name,
                        ideal_patient_type=revised,
                    )
                    clinic['suggested_email_body'] = body

                approved = verdict.get('approved', True)
                log(f"  Judge: {'APPROVED' if approved else 'REJECTED'}" +
                    (f" — {verdict.get('rejection_reason', '')}" if not approved else ""))
            except Exception as e:
                log(f"  Judge failed: {e} — proceeding with draft")
                clinic['judge_approved'] = 'True'
                clinic['judge_reason'] = ''

            try:
                draft_id = create_draft_fn(email, subject, body,
                                           GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH)
                clinic['gmail_draft_id'] = draft_id
                log(f"  Gmail draft created: {draft_id}")
            except Exception as e:
                log(f"  Gmail draft failed: {e}")
        else:
            log("  No email address — skipping Gmail draft.")


async def run_match_emails(args):
    """Match CQC person names against practitioner DB to find direct emails."""
    if not os.path.exists(args.output):
        log(f"Output file not found: {args.output}")
        return

    from practitioner_lookup import lookup_practitioner

    df = pd.read_csv(args.output, dtype=str)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ''
    df = df.fillna('')

    # Process rows that have a CQC person but no email match yet
    has_cqc = (
        (df['cqc_nominated_individual'].str.strip() != '') |
        (df['cqc_registered_manager'].str.strip() != '')
    )
    not_matched = df['decision_maker_email'].str.strip() == ''
    todo = df[has_cqc & not_matched]

    log(f"Email matching: {len(todo)} rows with CQC persons to match")
    if todo.empty:
        log("Nothing to do.")
        return

    found = 0
    for pos, (idx, row) in enumerate(todo.iterrows()):
        # Prefer nominated individual (decision-maker), fall back to registered manager
        name = (row.get('cqc_nominated_individual') or row.get('cqc_registered_manager') or '').strip()
        if not name:
            continue

        clinic = row.get('clinic_name', '?')
        log(f"[{pos+1}/{len(todo)}] {clinic} — looking up: {name}")

        match = lookup_practitioner(name, row.get('website_url', ''))
        if match.get('decision_maker_email'):
            found += 1
            log(f"  Found: {match['decision_maker_email']} ({match['decision_maker_name_matched']})")
            for key, val in match.items():
                df.at[idx, key] = val
            _safe_save(df, args.output)
        else:
            log(f"  Not found in DB")

    log(f"\nEmail matching complete: {found} / {len(todo)} found")
    log(f"CSV updated: {os.path.abspath(args.output)}")


_DOCTIFY_CONCURRENCY = 8  # parallel browser contexts


async def run_doctify_emails(args):
    """Scrape Doctify specialist profiles in parallel to find emails for CQC-matched people."""
    if not os.path.exists(args.output):
        log(f"Output file not found: {args.output}")
        return

    from playwright.async_api import async_playwright
    from doctify_specialist_lookup import _lookup_one

    df = pd.read_csv(args.output, dtype=str)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ''
    df = df.fillna('')

    has_cqc = (
        (df['cqc_nominated_individual'].str.strip() != '') |
        (df['cqc_registered_manager'].str.strip() != '')
    )
    has_doctify_url = df['doctify_profile_url'].str.startswith('http')
    not_checked = df['doctify_specialist_slug'].str.strip() == ''
    todo = df[has_cqc & has_doctify_url & not_checked]

    log(f"Doctify email lookup: {len(todo)} rows | concurrency={_DOCTIFY_CONCURRENCY}")
    if todo.empty:
        log("Nothing to do.")
        return

    semaphore = asyncio.Semaphore(_DOCTIFY_CONCURRENCY)
    csv_lock = asyncio.Lock()
    counter = {'done': 0, 'found': 0}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)

        async def process(idx, row):
            name = (row.get('cqc_nominated_individual') or
                    row.get('cqc_registered_manager') or '').strip()
            clinic_url = row.get('doctify_profile_url', '').strip()
            clinic = row.get('clinic_name', '?')

            async with semaphore:
                result = await _lookup_one(browser, clinic_url, name)

            async with csv_lock:
                counter['done'] += 1
                pos = counter['done']
                if result.get('email'):
                    counter['found'] += 1
                    df.at[idx, 'doctify_email'] = result['email']
                    df.at[idx, 'doctify_specialist_slug'] = result.get('doctify_slug', '')
                    log(f"[{pos}/{len(todo)}] {clinic}: {result['email']} "
                        f"(score {result.get('match_score', '?')})")
                else:
                    df.at[idx, 'doctify_specialist_slug'] = 'NOT_FOUND'
                    if pos % 20 == 0:
                        log(f"[{pos}/{len(todo)}] progress — {counter['found']} found so far")
                _safe_save(df, args.output)

        tasks = [process(idx, row) for idx, row in todo.iterrows()]
        await asyncio.gather(*tasks)
        await browser.close()

    log(f"\n{'='*50}")
    log(f"Doctify email lookup complete: {counter['found']} / {len(todo)} found")
    log(f"CSV updated: {os.path.abspath(args.output)}")


async def run_cqc_only(args):
    """Run CQC lookup on every row that hasn't been looked up yet. Saves after each clinic."""
    if not os.path.exists(args.output):
        log(f"Output file not found: {args.output}")
        return

    df = pd.read_csv(args.output, dtype=str)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ''
    df = df.fillna('')

    # '' = not yet checked; 'NOT_FOUND' = checked, not in CQC; anything else = found
    todo = df[df['cqc_location_id'].str.strip() == '']
    log(f"CQC lookup: {len(todo)} rows to process (of {len(df)} total)")
    if todo.empty:
        log("Nothing to do.")
        return

    matched = no_match = manager_found = nominated_found = 0

    for pos, (idx, row) in enumerate(todo.iterrows()):
        name = row.get('clinic_name', '?')
        location = row.get('location', '')
        log(f"\n[{pos+1}/{len(todo)}] {name}")

        cqc = lookup_cqc(name, location)
        for key, val in cqc.items():
            df.at[idx, key] = val

        if cqc.get('cqc_location_id'):
            matched += 1
            if cqc.get('cqc_nominated_individual'):
                nominated_found += 1
            if cqc.get('cqc_registered_manager'):
                manager_found += 1
            df.at[idx, 'salutation_name'] = (
                cqc.get('cqc_nominated_individual') or
                cqc.get('cqc_registered_manager') or
                row.get('salutation_name', '')
            )
        else:
            no_match += 1
            df.at[idx, 'cqc_location_id'] = 'NOT_FOUND'

        # Save after every clinic so progress survives interruption
        _safe_save(df, args.output)

    log(f"\n{'='*50}")
    log(f"CQC lookup complete:")
    log(f"  Matched in CQC : {matched} / {len(todo)}")
    log(f"  No CQC record  : {no_match}")
    log(f"  Nominated individual found : {nominated_found}")
    log(f"  Registered manager found   : {manager_found}")
    log(f"CSV updated: {os.path.abspath(args.output)}")


async def run_code_score_only(args):
    """Run code scoring on unknown rows. Marks code_passed (>40) or low_score (<=40)."""
    if not os.path.exists(args.output):
        log(f"Output file not found: {args.output}")
        return

    df = pd.read_csv(args.output)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ''
    df = df.fillna('')

    todo = df[df['status'] == 'unknown']
    log(f"Rows to code-score: {len(todo)} (of {len(df)} total)")
    if todo.empty:
        log("Nothing to do.")
        return

    passed = failed = 0
    for idx, row in todo.iterrows():
        clinic = row.to_dict()
        score = _code_score_clinic(clinic)
        df.at[idx, 'code_score'] = str(score)
        if score > 40:
            df.at[idx, 'status'] = 'code_passed'
            passed += 1
        else:
            df.at[idx, 'status'] = 'low_score'
            df.at[idx, 'filter_reason'] = f'code score {score} (below threshold)'
            df.at[idx, 'fit_score'] = str(score)
            failed += 1

    _safe_save(df, args.output)
    log(f"\nCode scoring complete: {passed} passed, {failed} rejected")
    log(f"CSV updated: {os.path.abspath(args.output)}")

    # Print sample of top code_passed rows for review
    passed_df = df[df['status'] == 'code_passed'].sort_values('code_score', ascending=False)
    log(f"\n--- Top 5 code_passed samples ---")
    for _, row in passed_df.head(5).iterrows():
        log(f"  [{int(float(row['code_score']))}] {row['clinic_name']} | specialists: {row['specialist_count']} | reviews: {row['review_count']} | tags: {str(row['specialty_tags'])[:60]}")


async def run_enrich_only(args):
    """Read existing CSV, enrich rows not yet drafted, rewrite CSV."""
    if not os.path.exists(args.output):
        log(f"Output file not found: {args.output}")
        return

    df = pd.read_csv(args.output)
    # Ensure all expected columns exist
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ''
    df = df.fillna('')

    skip_statuses = {'drafted', 'gmail_only', 'insufficient_info', 'pre_filtered', 'low_score', 'needs_manual_contact'}
    # Prefer code_passed rows; fall back to unknown for backward compatibility
    code_passed = df[df['status'] == 'code_passed']
    if not code_passed.empty:
        todo = code_passed
    else:
        todo = df[~df['status'].isin(skip_statuses)]
    if args.require_email:
        todo = todo[todo['contact_email'].str.strip() != '']
    if args.max_clinics:
        todo = todo.head(args.max_clinics)

    log(f"Rows to enrich: {len(todo)} (of {len(df)} total)")
    if todo.empty:
        log("Nothing to do.")
        return

    if not OPENROUTER_API_KEY:
        log("WARNING: OPENROUTER_API_KEY not set. Aborting.")
        return

    create_draft_fn = _setup_gmail()

    for pos, (idx, row) in enumerate(todo.iterrows()):
        clinic = row.to_dict()
        name = clinic.get('clinic_name', 'Unknown')
        log(f"\n[{pos+1}/{len(todo)}] {name}")

        website_text = ''
        if args.crawl:
            website_url = clinic.get('website_url', '').strip()
            if website_url:
                try:
                    log(f"  Crawling: {website_url}")
                    crawled = crawl_website(website_url)
                    pages = crawled.get('pages', [])
                    website_text = clean_and_cap(pages)
                    log(f"  Crawled {len(pages)} pages — {len(website_text)} chars extracted")
                    clinic['status'] = 'crawled'
                except Exception as e:
                    log(f"  Crawl failed: {e}")
                    clinic['status'] = 'crawl_failed'
                    clinic['error'] = str(e)
            else:
                log("  No website URL")

        if args.cqc and not clinic.get('cqc_location_id'):
            log("  CQC lookup...")
            cqc = lookup_cqc(clinic.get('clinic_name', ''), clinic.get('location', ''))
            clinic.update(cqc)
            # Use registered manager as salutation if found
            # Prefer nominated individual (lead clinician/owner) for salutation;
            # fall back to registered manager if not present
            clinic['salutation_name'] = (
                cqc.get('cqc_nominated_individual') or
                cqc.get('cqc_registered_manager') or
                clinic.get('salutation_name', '')
            )

        if not _has_sufficient_info(clinic):
            log("  Insufficient bio — skipping LLM")
            clinic['status'] = 'insufficient_info'
            for col in COLUMNS:
                if col in clinic:
                    df.at[idx, col] = _flatten(clinic[col])
            _safe_save(df, args.output)
            continue

        _enrich_and_draft(clinic, website_text, create_draft_fn)

        # Update the row and save immediately so progress survives interruption
        for col in COLUMNS:
            if col in clinic:
                df.at[idx, col] = _flatten(clinic[col])
        _safe_save(df, args.output)

    log(f"\nCSV updated: {os.path.abspath(args.output)}")
    _print_summary(df.to_dict('records'))


def _next_send_time(after: datetime, delay_minutes: float) -> datetime:
    """
    Return the next valid send time at least delay_minutes after `after`,
    staying within working windows: 09:00-12:00 and 14:00-17:00 Mon-Fri.
    """
    t = after + timedelta(minutes=delay_minutes)
    while True:
        # Skip weekends
        if t.weekday() >= 5:
            t = t.replace(hour=9, minute=0, second=0, microsecond=0)
            t += timedelta(days=(7 - t.weekday()))
            continue
        h = t.hour + t.minute / 60
        if h < 9:
            t = t.replace(hour=9, minute=0, second=0, microsecond=0)
        elif 12 <= h < 14:
            t = t.replace(hour=14, minute=0, second=0, microsecond=0)
        elif h >= 17:
            t = t.replace(hour=9, minute=0, second=0, microsecond=0)
            t += timedelta(days=1)
        else:
            break
    return t


async def run_send_approved(args):
    """Send approved auto-send drafts staggered across working hours."""
    if not os.path.exists(args.output):
        log(f"Output file not found: {args.output}")
        return
    if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
        log("Gmail credentials not found.")
        return

    from gmail_draft import send_draft, find_draft_by_subject

    df = pd.read_csv(args.output)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ''
    df = df.fillna('')

    to_send = df[
        (df['status'] == 'drafted') &
        (df['auto_send_eligible'].astype(str).str.lower() == 'true') &
        (df['judge_approved'].astype(str).str.lower() == 'true') &
        (df['email_sent_date'].fillna('').astype(str).str.strip() == '')
    ]

    log(f"Auto-send queue: {len(to_send)} emails")
    if to_send.empty:
        log("Nothing to send.")
        return

    delay_min = getattr(args, 'send_delay_min', 1)
    delay_max = getattr(args, 'send_delay_max', 3)
    now = datetime.now()
    send_at = _next_send_time(now, 0)
    dry_run = getattr(args, 'dry_run', False)

    for pos, (idx, row) in enumerate(to_send.iterrows()):
        name = row.get('clinic_name', 'Unknown')
        draft_id = str(row.get('gmail_draft_id', '')).strip()

        # Resolve draft ID if missing — search Gmail by subject
        if not draft_id:
            subject = str(row.get('suggested_subject', '')).strip()
            if subject:
                log(f"  No draft ID — searching Gmail for subject: {subject}")
                draft_id = find_draft_by_subject(subject, GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH)
                if draft_id:
                    df.at[idx, 'gmail_draft_id'] = draft_id
                    log(f"  Found draft: {draft_id}")
                else:
                    log(f"  Draft not found in Gmail — skipping")
                    send_at = _next_send_time(send_at, random.uniform(delay_min, delay_max))
                    continue

        wait_secs = max(0, (send_at - datetime.now()).total_seconds())
        log(f"\n[{pos+1}/{len(to_send)}] {name}")
        log(f"  Scheduled: {send_at.strftime('%a %d %b %H:%M:%S')}")

        if dry_run:
            log(f"  DRY RUN — would send draft {draft_id}")
        else:
            if wait_secs > 0:
                log(f"  Waiting {int(wait_secs//60)}m {int(wait_secs%60)}s...")
                time.sleep(wait_secs)
            try:
                send_draft(draft_id, GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH)
                df.at[idx, 'email_sent_date'] = datetime.now().strftime('%Y-%m-%d')
                df.at[idx, 'followup_status'] = 'sent_confirmed'
                _safe_save(df, args.output)
                log(f"  Sent at {datetime.now().strftime('%H:%M:%S')}")
            except Exception as e:
                log(f"  Send failed: {e}")

        # Random interval for next send
        gap = random.uniform(delay_min, delay_max)
        send_at = _next_send_time(send_at, gap)

    if not dry_run:
        log(f"\nDone. CSV updated.")


async def run_followup(args):
    """Sync Gmail sent status and optionally draft follow-ups."""
    if not os.path.exists(args.output):
        log(f"Output file not found: {args.output}")
        return

    if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
        log("Gmail credentials not found — cannot sync sent status.")
        return

    from gmail_sync import sync_and_followup

    df = pd.read_csv(args.output)
    for col in ['email_sent_date', 'email_thread_id', 'followup_draft_id', 'followup_status']:
        if col not in df.columns:
            df[col] = ''
    df = df.fillna('')

    dry_run = getattr(args, 'dry_run', False)
    mode = "Sent-box sync"
    if args.followup:
        mode = "Follow-up dry run (no drafts)" if dry_run else "Follow-up sync"
    log("=" * 50)
    log(mode)
    log("=" * 50)

    df = sync_and_followup(
        df,
        GOOGLE_CREDENTIALS_PATH,
        GOOGLE_TOKEN_PATH,
        followup_days=args.followup_days,
        create_drafts=args.followup,
        dry_run=dry_run,
    )

    if not dry_run:
        _safe_save(df, args.output)
        log(f"\nCSV updated: {os.path.abspath(args.output)}")
    else:
        log("\n(CSV not modified — dry run)")


async def run(args):
    if args.cqc_only:
        await run_cqc_only(args)
        return

    if args.match_emails:
        await run_match_emails(args)
        return

    if args.doctify_emails:
        await run_doctify_emails(args)
        return

    if args.enrich_only:
        await run_enrich_only(args)
        return

    if args.code_score_only:
        await run_code_score_only(args)
        return

    if args.send_approved:
        await run_send_approved(args)
        return

    if args.followup or args.sync_sent:
        await run_followup(args)
        return

    log("=" * 50)
    log("Clinic Sales Pipeline")
    log("=" * 50)
    log(f"Output    : {os.path.abspath(args.output)}")
    if args.max_clinics:
        log(f"Max clinics: {args.max_clinics}")

    # Step 1: Scrape Doctify
    log("\n-- Step 1: Scraping Doctify --")

    if args.start_url:
        url_configs = [{'url': args.start_url, 'pages': args.pages or 1}]
    else:
        url_configs = read_input_urls(pages_override=args.pages)
        if not url_configs:
            log("No URLs found in input_urls.csv and no --start-url given. Exiting.")
            return

    for cfg in url_configs:
        log(f"  {cfg['url']}  ({cfg['pages']} pages)")

    # Deduplicate against existing CSV
    seen_profiles = set()
    if os.path.exists(args.output):
        existing = pd.read_csv(args.output)
        if not args.start_url or args.append:
            seen_profiles = set(existing['doctify_profile_url'].dropna().tolist())
            log(f"Cross-check: {len(seen_profiles)} clinics already in CSV will be skipped")

    clinics = []       # non-pre-filtered, passed to LLM pipeline
    save_lock = asyncio.Lock()
    counters = {'saved': 0, 'filtered': 0}

    async def on_clinic_ready(clinic):
        """Called after each profile visit — pre-filter, classify, save."""
        key = clinic.get('doctify_profile_url', '')
        if not key:
            return
        reason = _pre_filter_clinic(clinic)
        if reason:
            clinic['status'] = 'pre_filtered'
            clinic['filter_reason'] = reason
            async with save_lock:
                counters['filtered'] += 1
        else:
            clinic.setdefault('status', 'unknown')
            async with save_lock:
                clinics.append(clinic)
        async with save_lock:
            counters['saved'] += 1
        append_result(clinic, args.output)

    await scrape_doctify(
        url_configs=url_configs,
        skip_profile_urls=seen_profiles,
        listing_delay=args.listing_delay,
        max_profile_concurrency=4,
        on_clinic_ready=on_clinic_ready,
    )

    total_saved = counters['saved']
    total_filtered = counters['filtered']
    log(f"\nScrape complete: {total_saved} new rows saved ({total_filtered} pre-filtered)")

    if args.scrape_only:
        log(f"Output: {os.path.abspath(args.output)}")
        _print_summary(clinics)
        return

    if args.max_clinics:
        clinics = clinics[:args.max_clinics]

    if not clinics:
        log("No clinics to enrich. Exiting.")
        return

    # Step 2 (optional): CQC lookup — find Registered Manager for each clinic
    if args.cqc:
        log("\n-- Step 2: CQC registry lookup --")
        for clinic in clinics:
            log(f"  {clinic.get('clinic_name', '?')}")
            cqc = lookup_cqc(clinic.get('clinic_name', ''), clinic.get('location', ''))
            clinic.update(cqc)
            # Prefer nominated individual (lead clinician/owner) for salutation;
            # fall back to registered manager if not present
            clinic['salutation_name'] = (
                cqc.get('cqc_nominated_individual') or
                cqc.get('cqc_registered_manager') or
                clinic.get('salutation_name', '')
            )

    # Step 3: Crawl + LLM
    log("\n-- Step 2: LLM enrichment --")

    if not OPENROUTER_API_KEY:
        log("WARNING: OPENROUTER_API_KEY not set. LLM step will be skipped.")

    create_draft_fn = _setup_gmail()

    for i, clinic in enumerate(clinics):
        name = clinic.get('clinic_name', 'Unknown')
        log(f"\n[{i+1}/{len(clinics)}] {name}")

        website_text = ''
        if args.crawl:
            website_url = clinic.get('website_url', '')
            if website_url:
                try:
                    log(f"  Crawling: {website_url}")
                    crawled = crawl_website(website_url)
                    pages = crawled.get('pages', [])
                    website_text = clean_and_cap(pages)
                    log(f"  Crawled {len(pages)} pages — {len(website_text)} chars extracted")
                    clinic['status'] = 'crawled'
                except Exception as e:
                    log(f"  Crawl failed: {e}")
                    clinic['status'] = 'crawl_failed'
                    clinic['error'] = str(e)
            else:
                log("  No website URL")

        if not _has_sufficient_info(clinic):
            log("  Insufficient bio — skipping LLM")
            clinic['status'] = 'insufficient_info'
            append_result(clinic, args.output)
            continue

        _enrich_and_draft(clinic, website_text, create_draft_fn)
        append_result(clinic, args.output)

    log("\n-- Done --")
    log(f"Results saved to: {os.path.abspath(args.output)}")
    _print_summary(clinics)


def _print_summary(clinics: list):
    by_status = {}
    for c in clinics:
        s = c.get('status', 'unknown')
        by_status[s] = by_status.get(s, 0) + 1
    log("\nSummary:")
    for status, count in sorted(by_status.items()):
        log(f"  {status}: {count}")


if __name__ == '__main__':
    asyncio.run(run(parse_args()))
