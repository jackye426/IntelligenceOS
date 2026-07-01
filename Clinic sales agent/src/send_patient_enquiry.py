#!/usr/bin/env python3
"""Create Gmail drafts for endometriosis patient referral enquiries.

Usage:
  python src/send_patient_enquiry.py           # create drafts
  python src/send_patient_enquiry.py --dry-run # preview only
"""

import argparse
import base64
import html as html_lib
import os
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.config import GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH
from src.gmail_draft import _get_service

SUBJECT = "Endometriosis appointment enquiry"
CC = "emmieflorey4@gmail.com"

BODY_TEMPLATE = """\
Hi {salutation},

Hope you are well.

I am getting in touch on behalf of our patient, copied here, who is seeking specialist support for endometriosis.

Could you please let us know whether this is something you would be able to help with, the services you offer for endometriosis patients, and the cost of an initial consultation or any relevant packages?

Please also let her know the best next step for arranging an appointment. Feel free to contact her directly for any clinical information or questions.

For future patient enquiries, we would also like to invite you to join DocMap, where patients can find your profile and contact your practice directly.

Best,
Admin
DocMap\
"""

# (consultant display name, to_email, salutation)
# Salutation: named person if email belongs to a named individual; otherwise consultant name
RECIPIENTS = [
    ("Miss Nadine Di Donato",          "sharon.phillips@ppsec.uk",          "Sharon"),
    ("Mr Ian Currie",                  "kgmedsec@gmail.com",                "Mr Currie"),
    ("Mr Nilesh Agarwal",              "shivnilesh@yahoo.com",              "Mr Agarwal"),
    ("Mr Elias Kovoor",                "debbie.coleman@kims.org.uk",        "Debbie"),
    ("Mr Montasser Mahran",            "montasser@doctors.org.uk",          "Mr Mahran"),
    ("Mr Martin Hirsch",               "admin@oxfordgynaecology.co.uk",     "the Oxford Gynaecology team"),
    ("Vasileios Minas",                "secretary.minas@gmail.com",         "Mr Minas"),
]


def _to_html(plain: str) -> str:
    parts = plain.split("\n\n")
    html_parts = []
    for part in parts:
        part = part.strip()
        if part:
            escaped = html_lib.escape(part).replace("\n", "<br>")
            html_parts.append(f"<p>{escaped}</p>")
    body = "\n".join(html_parts)
    style = ("<style>body{font-family:Arial,Helvetica,sans-serif;font-size:15px;"
             "color:#1a1a1a;max-width:620px;margin:0 auto;padding:24px 16px}"
             "p{line-height:1.65;margin:0 0 14px}</style>")
    return f"<html><head>{style}</head><body>{body}</body></html>"


def _create_draft(service, to_email: str, salutation: str) -> str:
    body = BODY_TEMPLATE.format(salutation=salutation)
    html = _to_html(body)

    msg = MIMEMultipart("alternative")
    msg["to"] = to_email
    msg["cc"] = CC
    msg["subject"] = SUBJECT
    msg.attach(MIMEText(html, "html", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = service.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()
    return draft["id"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"Drafts to create : {len(RECIPIENTS)}  (CC: {CC})\n")

    if args.dry_run:
        print("DRY RUN — no drafts created.\n")
        for consultant, email, salutation in RECIPIENTS:
            print(f"  {consultant:<35} -> {email}  (Hi {salutation})")
        return

    service = _get_service(GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH)
    for i, (consultant, email, salutation) in enumerate(RECIPIENTS, 1):
        draft_id = _create_draft(service, email, salutation)
        print(f"  [{i}] {consultant:<35} <{email}>  draft:{draft_id}")

    print(f"\nDone. {len(RECIPIENTS)} drafts created.")


if __name__ == "__main__":
    main()
