"""
Delete only the follow-up drafts we created (stored in followup_draft_id column)
and reset those rows so --followup will recreate them with the updated template.
"""
import csv
import json
import os
import sys

import pandas as pd
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/gmail.readonly',
]

sys.path.insert(0, os.path.dirname(__file__))
from utils import log

BASE = os.path.dirname(os.path.dirname(__file__))
CREDENTIALS_PATH = os.path.join(BASE, 'credentials', 'gmail-credentials.json')
TOKEN_PATH = os.path.join(BASE, 'credentials', 'token.json')
CSV_PATH = os.path.join(BASE, 'output', 'clinic_sales_results.csv')


def get_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH) as f:
            saved = json.load(f)
        if all(s in saved.get('scopes', []) for s in SCOPES):
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, 'w') as f:
            f.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)


def main():
    df = pd.read_csv(CSV_PATH)
    service = get_service()

    mask = df['followup_draft_id'].notna() & (df['followup_draft_id'].astype(str).str.strip() != '')
    rows = df[mask]
    log(f"Found {len(rows)} follow-up drafts to delete and reset.")

    deleted = 0
    failed = 0
    for idx, row in rows.iterrows():
        draft_id = str(row['followup_draft_id']).strip()
        clinic_name = row.get('clinic_name', '?')
        try:
            service.users().drafts().delete(userId='me', id=draft_id).execute()
            df.at[idx, 'followup_draft_id'] = ''
            df.at[idx, 'followup_status'] = 'sent_confirmed'
            deleted += 1
            log(f"  Deleted follow-up draft for {clinic_name}")
        except Exception as e:
            failed += 1
            log(f"  FAILED to delete draft for {clinic_name}: {e}")

    df.to_csv(CSV_PATH, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_ALL)
    log(f"\nDeleted: {deleted}, Failed: {failed}")
    log(f"CSV updated — run: python src/main.py --followup   to recreate drafts.")


if __name__ == '__main__':
    main()
