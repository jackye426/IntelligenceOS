#!/usr/bin/env python3
"""Create Gmail newsletter drafts for all Live in-network practitioners.

Usage:
  python src/send_newsletter.py           # create drafts
  python src/send_newsletter.py --dry-run # preview recipients, no drafts
"""

import argparse
import base64
import os
import sys
from email.mime.text import MIMEText

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.config import GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH
from src.gmail_draft import _get_service

SUBJECT = "A brief update from DocMap"

BODY_TEMPLATE = """\
Hi {first_name},

Hope you are well. Apologies that it has been a little while since our last update.

We wanted to share a brief and honest picture of what we have been working on.

Over the past few months, our main focus has been building patient demand. Bringing together a strong clinician network was the first step, but the harder part is helping the right patients find the right specialist and feel confident enough to enquire or book.

That has taken longer than expected, but we are starting to see real momentum.

## Bringing patients in

To focus our efforts, we have chosen endometriosis as our first patient market. It is an area where patients often face a long route to diagnosis and treatment, and where many eventually look privately for specialist support.

This does not change DocMap’s wider direction. It is where we are concentrating our marketing first, so that we can learn quickly and build a repeatable model for other patient groups and specialties.

We have been refining our website, patient messaging, and content around the questions patients are actually asking when they are unsure where to turn.

A major part of this has been short-form educational content and clinician interviews. Over the past two months, our content has generated more than 530,000 organic views, alongside thousands of likes and saves. We are seeing a clear appetite for practical, expert-led information that helps patients understand their options and what to do next.

If you would be open to being featured in future content, please reply. The strongest content comes from clinicians helping patients make sense of difficult decisions.

We have also developed an AI-led matching service that considers a patient’s circumstances, symptoms, and care needs, then explains why a particular clinician may be a suitable fit. So far, this has routed patient demand representing more than £600,000 in potential care pathways.

## What we are building

Alongside demand generation, we are building tools that make the journey from first question to appointment clearer for patients and more useful for clinics.

For practices, we have introduced our AI Clinic Conversion tool. It can sit on your website, answer questions about your services, clinicians, and pricing, and help suitable patients take the next step.

Just as importantly, it shows you what visitors are asking, where they hesitate, what leads them to enquire, and where interest is lost before booking. Over time, it learns from those interactions to improve the patient experience and conversion journey.

You can read more on our AI Concierge page, or reply directly if you would like to see how it could work for your practice.

## A recent highlight

An interview with endometriosis specialist Liz Bruen received 371,000 views, more than 30,000 likes, around 600 comments, and over 20,000 saves. It is a useful example of how far clear, clinician-led information can travel when patients need it.

## What is next

Next month, we will be introducing a major AI capability that will make DocMap more useful not only for booking, but also for helping patients understand their options earlier in their journey.

We know the value of DocMap ultimately comes down to helping the right patients reach your practice. That remains the priority.

Best,
The DocMap team\
"""

# Live practitioners only. Rows with duplicate emails keep the first occurrence.
# Laura Tilt excluded (no email on record).
PRACTITIONERS = [
    ("Parveen Verasingam",   "endo@parveenverasingam.uk"),
    ("Joe Alvarez",           "joe@theguthealthclinic.com"),
    ("Alice Twomey",          "alice@theguthealthclinic.com"),
    ("Amy Buckley",           "amy@theguthealthclinic.com"),
    ("Dr Emily Porter",       "emily@theguthealthclinic.com"),
    ("Gabrielle Morse",       "gabrielle@theguthealthclinic.com"),
    ("Pratima Goodfellow",    "pratima@theguthealthclinic.com"),
    ("Liz Bruen",             "liz.bruen@gmail.com"),
    ("Esha Saha",             "Esha-info@thelunaclinic.com"),
    ("Ali Abbara",            "ali-info@thelunaclinic.com"),
    ("Vikram Talaulikar",     "vikram-info@thelunaclinic.com"),
    ("Sophie Clarke",         "sophie-info@thelunaclinic.com"),
    ("Bassel Wattar",         "info@thelunaclinic.com"),
    ("Eloise Garbutt",        "bookings@theguthealthclinic.com"),
    ("Michael Adamczyk",      "adamczykpa@hcahealthcare.co.uk"),
    ("Ines Jabir",            "enquiries@mynutritionbalance.com"),
    ("Talia Cecchele",        "info@taliacecchele.com"),
    ("Maeve Hanan",           "info@dieteticallyspeaking.clinic"),
    ("Sarah Idakwo",          "sarah@thehungrynutritionist.com"),
    ("John Wilson",           "james.wilson@ukclinicdemo.co.uk"),
    ("Georgina Broinowski",   "georgina@dietitianfit.co.uk"),
    ("Isabella Alfonso",      "isabella@dietitianfit.co.uk"),
    ("Alicia Du Preez",       "alicia@dietitianfit.co.uk"),
    ("Katerina Ageridou",     "katerina@dietitianfit.co.uk"),
    ("Marizaan Du Toit",      "karine@dietitianfit.co.uk"),   # karine@ shared — first occurrence used
    ("Reema Pillai",          "reema@dietitianfit.co.uk"),
    ("Tara Bruni",            "tarabruni@tarabruni.com"),
    ("Sophie Corbett",        "sophie@mentalhealthdietitians.com"),
    ("Kate Hilton",           "info@dietsdebunked.co.uk"),
    ("Simone Rofena",         "rofenagynecologist@gmail.com"),
    ("Kate Costello",         "info@katecostello.co.uk"),
    ("Rachael Colley",        "rachael@thelonghauldietitian.co.uk"),
    ("Omar Shaikh",           "info@drshaikhcardiology.co.uk"),
    ("Ian Loke",              "iloke4@gmail.com"),
    ("Kinesh Patel",          "kinesh.patel@gmail.com"),
    ("Jacqueline Bailey",     "jacqueline@resolvingpain.co.uk"),
    ("Arjun Prakash",         "enquiries@harmonygutandliver.com"),
    ("Ibrahim Al Bakir",      "doctor@chelseagastro.co.uk"),
    ("David Griffiths",       "david@octaviahealthcare.co.uk"),
    ("Daniel Jones",          "dan.jones8@nhs.net"),
    ("Gregory Premetis",      "contact@gpremetis.com"),
    ("Pablo Robles",          "contact@pabloroblespsychologist.co.uk"),
    ("Vasileios Minas",       "secretary.minas@gmail.com"),
    ("Panicos Shangaris",     "panicos@shangaris.com"),
    ("Mahantesh Karoshi",     "info@mahanteshkaroshi.co.uk"),
    ("Kunal Rathod",          "mrkunalrathod@gmail.com"),
    ("Jo Gee",                "marketing@drjogeepsychotherapy.co.uk"),
    ("Raquel Britzke",        "assistant@raquelbritzke.com"),
    ("Helen Phadnis",         "info@thebespokenutritioncoach.co.uk"),
    ("Laura Vincent",         "laura@theendometriosisdietitian.com"),
    ("Gina Giebner",          "ginag@therehabdietitian.com"),
    ("Liam Grisley",          "drliamgrisley@gmail.com"),
    ("Rania Salman",          "info@londondietitian.co.uk"),
    ("Veronica Giudice",      "hello@mindbodyandsoulweightlossclinic.co.uk"),
    ("Aleks Jagiello",        "info@thedigitaldietitian.co.uk"),
    ("Yusuf Hammad",          "yusufull.nutrition@gmail.com"),
    ("Sascha Landskron",      "sascha@uninutrition.co.uk"),
    ("Bethany Willson",       "bethany@br-nutritionclinic.com"),
    ("Laura Malone",          "dietitianlauramalone@gmail.com"),
    ("Candice ONeil",         "admin@onticpsychology.com"),
    ("Giuseppe Scapellato",   "info@gscapellatonutrition.com"),
    ("Fredrica Windless",     "info@fredricawindless.com"),
    ("Graeme Syme",           "graeme@ibsdietsolutions.com"),
    ("Heather Daniels",       "heather@expertdietadvice.com"),
    ("Clementine Vaughan",    "info@thirdsister.co.uk"),
    ("Omar Kowlessar",        "dr.okowlessar@gmail.com"),
    ("Lisa Poole",            "business@precisiondietetics.co.uk"),
    ("Maria Kolotourou",      "hello@yourgreekdietitian.com"),
    ("Saira Khan",            "saira@trustmeimadietitian.co.uk"),
    ("Jodie Relf",            "info@thepcosdietitian.co.uk"),
    ("Kiki Lordanidou",       "info@harleystreet-psychologist.co.uk"),
    ("Shreelata Datta",       "statta102@gmail.com"),
    ("Leiya Lemkey",          "drlpsychology1@gmail.com"),
]

_TITLE_PREFIXES = ("Dr ", "Mr ", "Mrs ", "Ms ", "Prof ", "Professor ")


def _first_name(full_name: str) -> str:
    name = full_name.strip()
    for prefix in _TITLE_PREFIXES:
        if name.lower().startswith(prefix.lower()):
            name = name[len(prefix):]
            break
    return name.split()[0].capitalize()


def _body_to_html(plain: str) -> str:
    """Convert the newsletter body (plain text + ## headings) to styled HTML."""
    import html as html_lib

    style = """
    <style>
      body { font-family: Arial, Helvetica, sans-serif; font-size: 15px;
             color: #1a1a1a; max-width: 620px; margin: 0 auto; padding: 24px 16px; }
      h2   { font-size: 17px; color: #0a0a0a; margin-top: 28px; margin-bottom: 6px; }
      p    { line-height: 1.65; margin: 0 0 14px; }
    </style>
    """

    AI_CLINIC_URL = "https://docmap.co.uk/clinic"

    parts = plain.split("\n\n")
    html_parts = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.startswith("## "):
            heading = html_lib.escape(part[3:])
            html_parts.append(f"<h2>{heading}</h2>")
        else:
            escaped = html_lib.escape(part).replace("\n", "<br>")
            escaped = escaped.replace(
                "AI Clinic Conversion tool",
                f'<a href="{AI_CLINIC_URL}">AI Clinic Conversion tool</a>',
            )
            escaped = escaped.replace(
                "An interview with endometriosis specialist Liz Bruen",
                '<a href="https://www.tiktok.com/@docmap/video/7630900114982210838">'
                "An interview with endometriosis specialist Liz Bruen</a>",
            )
            html_parts.append(f"<p>{escaped}</p>")

    body_html = "\n".join(html_parts)
    return f"<html><head>{style}</head><body>{body_html}</body></html>"


def _create_draft(service, to_email: str, first_name: str) -> str:
    body = BODY_TEMPLATE.format(first_name=first_name)
    html = _body_to_html(body)
    msg = MIMEText(html, "html", "utf-8")
    msg["to"] = to_email
    msg["subject"] = SUBJECT
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = service.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()
    return draft["id"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print recipients without creating drafts")
    args = parser.parse_args()

    # Deduplicate by lower-cased email (preserves first occurrence)
    seen: set[str] = set()
    recipients: list[tuple[str, str]] = []
    skipped_dupes: list[tuple[str, str]] = []
    for full_name, email in PRACTITIONERS:
        key = email.lower()
        if key in seen:
            skipped_dupes.append((full_name, email))
        else:
            seen.add(key)
            recipients.append((full_name, email))

    print(f"Recipients : {len(recipients)}")
    if skipped_dupes:
        print(f"Skipped (duplicate email):")
        for name, email in skipped_dupes:
            print(f"  {name} <{email}>")
    print()

    if args.dry_run:
        print("DRY RUN — no drafts created.\n")
        for full_name, email in recipients:
            print(f"  {_first_name(full_name):<18}  {email}")
        return

    service = _get_service(GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH)
    created = 0
    for full_name, email in recipients:
        first = _first_name(full_name)
        draft_id = _create_draft(service, email, first)
        print(f"  [{created + 1:>2}] {full_name:<28} <{email}>  draft:{draft_id}")
        created += 1

    print(f"\nDone. {created} drafts created in Gmail.")


if __name__ == "__main__":
    main()
