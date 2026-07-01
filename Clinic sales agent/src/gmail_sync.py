"""
Syncs Gmail sent-box status back to the clinic CSV and creates follow-up drafts.

Two operations:
  sync_sent      — For each clinic with a contact_email, find the original
                   campaign email in the sent box and record email_sent_date
                   + email_thread_id.
  draft_followups — For clinics emailed N+ days ago with no reply, create a
                   follow-up draft as a reply in the original thread.
"""

import base64
import json as _json
import os
from datetime import date, datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
import html as html_lib

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import sys
sys.path.insert(0, os.path.dirname(__file__))
from utils import log

SCOPES = [
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/gmail.readonly',
]

_service = None
_my_email = None


def _get_service(credentials_path: str, token_path: str):
    global _service
    if _service is not None:
        return _service

    creds = None

    # Only reuse a saved token if it covers both required scopes
    if os.path.exists(token_path):
        with open(token_path) as f:
            saved = _json.load(f)
        saved_scopes = saved.get('scopes', [])
        if all(s in saved_scopes for s in SCOPES):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        else:
            log("Saved Gmail token is missing required scopes — re-authorising...")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as f:
            f.write(creds.to_json())

    _service = build('gmail', 'v1', credentials=creds)
    return _service


def _get_my_email(service) -> str:
    global _my_email
    if _my_email is None:
        profile = service.users().getProfile(userId='me').execute()
        _my_email = profile.get('emailAddress', '')
    return _my_email


def _find_sent_email(service, contact_email: str) -> dict | None:
    """
    Find the original campaign email sent to contact_email.
    Searches for subject:"AI concierge pilot for" to stay within campaign emails.
    Returns the oldest match (original outreach, not a follow-up).
    Returns {'thread_id': str, 'sent_date': 'YYYY-MM-DD'} or None.
    """
    query = f'in:sent to:{contact_email} subject:"AI concierge pilot for"'
    try:
        result = service.users().messages().list(
            userId='me', q=query, maxResults=20
        ).execute()
        messages = result.get('messages', [])
        if not messages:
            return None

        # Gmail returns newest-first; take the oldest (original outreach)
        msg_id = messages[-1]['id']
        msg = service.users().messages().get(
            userId='me', id=msg_id, format='metadata',
            metadataHeaders=['Date', 'Subject']
        ).execute()

        thread_id = msg.get('threadId')
        headers = {h['name']: h['value'] for h in msg['payload']['headers']}
        date_str = headers.get('Date', '')

        try:
            dt = parsedate_to_datetime(date_str).astimezone(timezone.utc)
            sent_date = dt.strftime('%Y-%m-%d')
        except Exception:
            sent_date = date_str

        return {'thread_id': thread_id, 'sent_date': sent_date}

    except Exception as e:
        log(f"    Gmail search error for {contact_email}: {e}")
        return None


def _thread_has_reply(service, thread_id: str, my_email: str) -> bool:
    """True if the thread contains a message whose From is not my_email."""
    try:
        thread = service.users().threads().get(
            userId='me', id=thread_id, format='metadata',
            metadataHeaders=['From']
        ).execute()
        messages = thread.get('messages', [])
        for msg in messages[1:]:  # First message is our original send
            headers = {h['name']: h['value'] for h in msg['payload']['headers']}
            sender = headers.get('From', '')
            if my_email.lower() not in sender.lower():
                return True
        return False
    except Exception:
        return False


FOLLOWUP_TEMPLATE = """\
Dear {clinic_name} team,

I hope you are well.

I just wanted to follow up on my previous note. We're speaking with a small number of clinics about shaping an AI concierge that helps answer patient questions clearly and convert more website enquiries into bookings.

Do you think your practice could benefit from turning more patient website visits into booked appointments?

Best,
Jack\
"""

DOCMAP_URL = 'https://search.docmap.co.uk/clinic'


def _to_html(plain: str) -> str:
    escaped = html_lib.escape(plain)
    escaped = escaped.replace('DocMap', f'<a href="{DOCMAP_URL}">DocMap</a>', 1)
    paragraphs = escaped.split('\n\n')
    body_html = ''.join(f'<p>{p.replace(chr(10), "<br>")}</p>' for p in paragraphs)
    return f'<html><body>{body_html}</body></html>'


def _create_followup_draft(service, clinic: dict, thread_id: str, sent_date: str) -> str:
    """Create a follow-up as a reply in the original Gmail thread. Returns draft ID."""
    clinic_name = clinic.get('clinic_name', 'the team')
    contact_email = clinic.get('contact_email', '').strip()

    body = FOLLOWUP_TEMPLATE.format(clinic_name=clinic_name)
    subject = f"Re: AI concierge pilot for {clinic_name}"

    msg = MIMEText(_to_html(body), 'html', 'utf-8')
    msg['to'] = contact_email
    msg['subject'] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = service.users().drafts().create(
        userId='me',
        body={'message': {'raw': raw, 'threadId': thread_id}},
    ).execute()
    return draft['id']


def sync_and_followup(
    df,
    credentials_path: str,
    token_path: str,
    followup_days: int = 2,
    create_drafts: bool = True,
    dry_run: bool = False,
):
    """
    Update df in-place:
      1. For each row with a contact_email, find the sent campaign email and
         record email_sent_date + email_thread_id.
      2. If create_drafts=True (and dry_run=False), draft follow-ups for rows
         that are followup_days+ old and have no reply yet.
      3. If dry_run=True, print the eligibility breakdown without creating drafts.

    Returns the updated DataFrame.
    """
    service = _get_service(credentials_path, token_path)
    my_email = _get_my_email(service)
    log(f"Authenticated as: {my_email}")

    today = date.today()
    cutoff = today - timedelta(days=followup_days)

    synced = drafted = skipped_replied = skipped_recent = already_done = 0

    for idx, row in df.iterrows():
        contact_email = str(row.get('contact_email', '')).strip()
        if not contact_email or '@' not in contact_email:
            continue

        clinic_name = str(row.get('clinic_name', 'Unknown'))
        current_status = str(row.get('followup_status', ''))

        # --- Sync sent status if not already recorded ---
        thread_id = str(row.get('email_thread_id', '')).strip()
        sent_date = str(row.get('email_sent_date', '')).strip()

        if not thread_id:
            sent_info = _find_sent_email(service, contact_email)
            if not sent_info:
                continue
            thread_id = sent_info['thread_id']
            sent_date = sent_info['sent_date']
            if not dry_run:
                df.at[idx, 'email_thread_id'] = thread_id
                df.at[idx, 'email_sent_date'] = sent_date
                if current_status not in ('followup_drafted', 'replied'):
                    df.at[idx, 'followup_status'] = 'sent_confirmed'
                    current_status = 'sent_confirmed'
            synced += 1
            log(f"  {clinic_name}: sent on {sent_date}")
        else:
            log(f"  {clinic_name}: already recorded ({sent_date})")

        if not create_drafts:
            continue

        # Skip if follow-up already handled
        if current_status in ('followup_drafted', 'replied'):
            already_done += 1
            continue

        # Skip if sent too recently
        try:
            sent_dt = datetime.strptime(sent_date, '%Y-%m-%d').date()
        except Exception:
            continue

        if sent_dt > cutoff:
            skipped_recent += 1
            log(f"    -> sent {(today - sent_dt).days}d ago — too recent")
            continue

        # Skip if the clinic already replied
        if _thread_has_reply(service, thread_id, my_email):
            if not dry_run:
                df.at[idx, 'followup_status'] = 'replied'
            skipped_replied += 1
            log(f"    -> reply received, skipping")
            continue

        # Eligible for follow-up
        if dry_run:
            drafted += 1
            log(f"    -> WOULD draft follow-up (sent {(today - sent_dt).days}d ago)")
        else:
            try:
                clinic = row.to_dict()
                draft_id = _create_followup_draft(service, clinic, thread_id, sent_date)
                df.at[idx, 'followup_draft_id'] = draft_id
                df.at[idx, 'followup_status'] = 'followup_drafted'
                drafted += 1
                log(f"    -> follow-up draft created: {draft_id}")
            except Exception as e:
                log(f"    -> follow-up draft failed: {e}")

    log(f"\nSync: {synced} new sent emails found")
    if create_drafts:
        if dry_run:
            log(f"\n--- DRY RUN — no drafts created ---")
        log(f"{'Would draft' if dry_run else 'Follow-ups drafted'} : {drafted}")
        log(f"Skipped (replied)              : {skipped_replied}")
        log(f"Skipped (< {followup_days}d)             : {skipped_recent}")
        log(f"Already done                   : {already_done}")
        if dry_run and drafted:
            log(f"\nRun with --followup (without --dry-run) to create {drafted} draft(s).")

    return df
