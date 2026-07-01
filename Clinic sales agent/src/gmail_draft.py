import base64
import html as html_lib
import os
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.compose']

_service = None


def _get_service(credentials_path: str, token_path: str):
    global _service
    if _service is not None:
        return _service

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as f:
            f.write(creds.to_json())

    _service = build('gmail', 'v1', credentials=creds)
    return _service


DOCMAP_URL = 'https://search.docmap.co.uk/clinic'


def _to_html(plain: str) -> str:
    escaped = html_lib.escape(plain)
    # Embed hyperlink on the first occurrence of "DocMap"
    escaped = escaped.replace(
        'DocMap',
        f'<a href="{DOCMAP_URL}">DocMap</a>',
        1,
    )
    paragraphs = escaped.split('\n\n')
    body_html = ''.join(f'<p>{p.replace(chr(10), "<br>")}</p>' for p in paragraphs)
    return f'<html><body>{body_html}</body></html>'


def find_draft_by_subject(subject: str, credentials_path: str, token_path: str) -> str:
    """Find a Gmail draft ID by subject line, paginating through all drafts."""
    service = _get_service(credentials_path, token_path)
    try:
        page_token = None
        while True:
            kwargs = {'userId': 'me', 'maxResults': 100}
            if page_token:
                kwargs['pageToken'] = page_token
            result = service.users().drafts().list(**kwargs).execute()
            for d in result.get('drafts', []):
                detail = service.users().drafts().get(
                    userId='me', id=d['id'], format='metadata',
                    metadataHeaders=['Subject']
                ).execute()
                headers = {h['name'].lower(): h['value'] for h in detail['message']['payload'].get('headers', [])}
                if headers.get('subject', '') == subject:
                    return d['id']
            page_token = result.get('nextPageToken')
            if not page_token:
                break
    except Exception:
        pass
    return ''


def send_draft(draft_id: str, credentials_path: str, token_path: str) -> str:
    """Send an existing Gmail draft by its ID. Returns the sent message ID."""
    service = _get_service(credentials_path, token_path)
    result = service.users().drafts().send(
        userId='me', body={'id': draft_id}
    ).execute()
    return result.get('id', '')


def create_draft(to_email: str, subject: str, body: str,
                 credentials_path: str, token_path: str) -> str:
    service = _get_service(credentials_path, token_path)
    msg = MIMEText(_to_html(body), 'html', 'utf-8')
    msg['to'] = to_email
    msg['subject'] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = service.users().drafts().create(
        userId='me', body={'message': {'raw': raw}}
    ).execute()
    return draft['id']
