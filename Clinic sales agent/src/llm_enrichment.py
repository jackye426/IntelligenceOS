import json
import re
import openai

# Location/branch suffixes commonly appended to clinic names
_BRANCH_SUFFIX = re.compile(
    r'\s*[-–]\s*(harley street|london|city|west|east|north|south|central|richmond|'
    r'wimbledon|chelsea|kensington|mayfair|marylebone|belgravia|canary wharf|'
    r'moorgate|shoreditch|islington|fulham|putney|clapham|brixton|'
    r'oxford street|portland place|wimpole street|great portland street|'
    r'fitzrovia|soho|covent garden|victoria|pimlico|'
    r'\w+ street|\w+ road|\w+ lane|\w+ place|\w+ square|\w+ avenue'
    r')\s*$',
    re.IGNORECASE,
)
_PARENTHETICAL = re.compile(r'\s*\((?:part of |crossrail place|[^)]{1,30})\)\s*$', re.IGNORECASE)


def clean_clinic_name(name: str) -> str:
    """Return a natural short form of the clinic name for use in salutations."""
    name = name.strip()
    # Strip parenthetical branch labels e.g. "(Crossrail Place)", "(part of Circle Health Group)"
    name = _PARENTHETICAL.sub('', name)
    # Strip location suffix after " - " e.g. "London Gynaecology - Richmond"
    name = _BRANCH_SUFFIX.sub('', name)
    # Also strip plain " - Location" where location is a single capitalised word
    name = re.sub(r'\s*-\s+[A-Z][a-z]+$', '', name)
    return name.strip()

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL
from utils import log

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = openai.OpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url='https://openrouter.ai/api/v1',
        )
    return _client


def _parse_json(text: str) -> dict:
    text = text.strip()
    # Strip markdown code fences if present
    match = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', text)
    if match:
        text = match.group(1)
    return json.loads(text)


SYSTEM_PROMPT = """\
You are helping Jack from DocMap assess private clinics for a sales outreach campaign.

DocMap builds an AI chatbot for private clinic websites. It answers patient questions promptly,
captures useful context about the patient's situation, and passes warmer, better-qualified
enquiries to the clinic team for personal follow-up. The core problem it solves: patients often
have serious intent but hesitate before contacting a clinic because they are unsure whether their
concern is suitable, what the first step should be, or what to ask. The chatbot reduces that
friction and converts more website visits into booked appointments.

Jack is looking for premium private clinics as design partners. Specialty is open: what matters
is clinic size, patient volume, and whether the practice can benefit from and afford a SaaS tool.

## Scoring rubric — fit_score 0-100

The core question: can this clinic afford to pay DocMap a meaningful monthly fee, and would
the tool pay for itself? Think in terms of revenue capacity — either high-value procedures
(where one extra conversion per month more than covers a SaaS fee) or sufficient patient
volume with frequent treatments. A solo IVF consultant charging £5-8k per cycle is a strong
candidate. A busy dermatology clinic with ten consultants seeing high volumes is equally valid.
Team size is a signal, not a gate.

HIGH FIT (70-100): Genuinely private clinical practice where the economics work. Either the
  procedures are high-value enough that a handful of extra conversions per month justifies a
  monthly fee, or the volume is high enough that the tool pays for itself quickly. Any clinical
  specialty qualifies. Pathway complexity (patients unsure which service or clinician to choose,
  or anxious about the process) is a strong plus — that is exactly where the chatbot adds value.

MEDIUM FIT (40-69): Private clinical practice where the economics could work but there is
  uncertainty — lower procedure values with limited evidence of volume, or a mixed model
  (some private, some NHS or GP) that dilutes the opportunity.

LOW FIT (10-39): The numbers probably do not work — very low procedure values, very small
  practice, or primarily aesthetic / cosmetic with no clear clinical pathway where patient
  guidance adds value.

VERY LOW / EXCLUDE (0-9): NHS or hospital-trust setting; holistic / wellness only
  (acupuncture, osteopathy, homeopathy, reflexology, or similar with no clinical procedures);
  purely cosmetic aesthetics with no named medical specialists; large corporate hospital group
  (HCA, Spire, Ramsay, BMI, Circle, Nuffield, Bupa) where the purchasing decision is not
  held by the clinic itself.

## Personalisation field (empty string if fit_score <= 60)

One field is inserted into the outreach email:

  "We help {ideal_patient_type} find the right private clinic, and {clinic_name} stood
   out as the kind of clinic many of these patients may be looking for."

**ideal_patient_type** — who this clinic primarily serves, described in their own terms (5-10 words)

Rules:
- Read the clinic's bio carefully. What does it LEAD WITH? What patient journey does it describe
  most prominently? Use that — not a generic category.
- Describe the patient by their CONDITION or GOAL, not their demographic. Avoid "women aged 35-45"
  or "middle-aged men" — use "people exploring fertility treatment" or "men with urological concerns".
- The phrase must feel immediately recognisable to the clinic — they should read it and think
  "yes, that is exactly our patient."
- For multi-specialty clinics, pick the ONE patient journey the clinic is most focused on or
  most proud of based on the bio. Do not list multiple specialties.
- Must connect naturally to the idea that DocMap helps this group "find the right clinic."
- 5-10 words, lowercase, no full stop.

BAD — too generic: "patients seeking private specialist care"
BAD — demographic-led: "women aged 35 to 45 with fertility concerns"
BAD — lists too much: "people with joint pain, skin conditions, or cardiac symptoms"

GOOD — condition/goal-led, specific to bio:
  "people exploring IVF, egg freezing, or fertility treatment"
  "men with urological symptoms or prostate concerns"
  "people with a skin condition or concern about a mole or lesion"
  "people with unexplained cardiac symptoms or chest pain"
  "people deciding whether to go private for a specialist musculoskeletal condition"
  "people looking for a private gynaecology or women's health specialist"

Return strict JSON only — no markdown fences, no commentary:
{
  "clinic_summary": string (2-3 sentences describing what the clinic does),
  "relevant_services": array of strings (key services, based on what they emphasise),
  "key_people": array of strings (named clinicians if found, else empty array),
  "fit_score": number 0-100,
  "fit_reason": string (specific reason for this score — cite team size, procedures, red flags),
  "filter_reason": string (if fit_score <= 60, the primary disqualifier; else empty string),
  "best_sales_angle": string (strongest reason to reach out),
  "possible_objection": string (most likely pushback from this clinic),
  "ideal_patient_type": string
}\
"""

EMAIL_TEMPLATE = """\
Dear {salutation_name} team,

I hope you are well. I'm Jack from DocMap. We help {ideal_patient_type} find the right private clinic, and {salutation_name} stood out as a strong option for patients looking for this kind of care.

One pattern we see is that patients are interested, but often compare multiple clinics and hesitate because they are unsure about fit, services, fees, what to ask, or the right next step. Do you see the same with your enquiries?

We are exploring whether a real-time website assistant could help clinics answer common questions, explain what makes their care relevant, capture useful context, and help more suitable patients move from browsing to booking. Would you be open to a short conversation?

Best,
Jack\
"""


def enrich_clinic(clinic: dict, website_text: str) -> dict:
    client = _get_client()
    user_msg = _build_user_message(clinic, website_text)

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=OPENROUTER_MODEL,
                messages=[
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': user_msg},
                ],
                temperature=0.4,
                response_format={'type': 'json_object'},
                timeout=60,
            )
            result = _parse_json(response.choices[0].message.content)

            # Assemble the full email from the template + LLM personalisation fields
            clinic_name = clinic.get('clinic_name', 'the team')
            salutation_name = clean_clinic_name(clinic_name)
            result['salutation_name'] = salutation_name
            ideal_patient_type = result.get('ideal_patient_type', 'patients').strip()
            result['suggested_subject'] = f"{salutation_name} - quick note about patient enquiries"
            result['suggested_email_body'] = EMAIL_TEMPLATE.format(
                clinic_name=clinic_name,
                salutation_name=salutation_name,
                ideal_patient_type=ideal_patient_type,
            )
            return result

        except json.JSONDecodeError as e:
            if attempt == 0:
                log(f"  JSON parse error on attempt 1, retrying: {e}")
                continue
            raise
    return {}


_JUDGE_PROMPT = """\
You are reviewing the opening paragraph of a cold outreach email:

  "I hope you are well. I'm Jack from DocMap. We help {ideal_patient_type} find the right
   private clinic, and {clinic_name} stood out as a strong option for patients looking for
   this kind of care."

Your ONLY job: does this paragraph read naturally as a whole? Specifically, does the phrase
"{ideal_patient_type}" flow naturally in the sentence it appears in, and does that sentence
connect naturally with the two sentences before it?

Approve if the paragraph reads as a natural, fluent piece of writing.
Reject ONLY if:
- The ideal_patient_type phrase is grammatically broken in context
- The sentence reads nonsensically when the three sentences are read together
- The phrase is so generic it says nothing ("patients", "people seeking care" with no qualifier)

Do NOT flag clinic names, salutations, length, tone, or anything outside of naturalness.
When in doubt, approve.

Return strict JSON only:
{
  "approved": boolean,
  "rejection_reason": string (specific issue if rejected; empty string if approved),
  "revised_ideal_patient_type": string (corrected phrase only if broken or blank; empty string otherwise)
}\
"""


def judge_email(clinic_name: str, salutation_name: str, ideal_patient_type: str, email_body: str) -> dict:
    """Independent LLM review of the assembled email. Returns approval decision."""
    client = _get_client()
    user_msg = (
        f"Clinic name (full): {clinic_name}\n"
        f"Salutation used: Dear {salutation_name} team\n"
        f"Ideal patient type used: {ideal_patient_type}\n\n"
        f"Full email:\n{email_body}"
    )
    try:
        response = client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=[
                {'role': 'system', 'content': _JUDGE_PROMPT},
                {'role': 'user', 'content': user_msg},
            ],
            temperature=0.2,
            response_format={'type': 'json_object'},
            timeout=30,
        )
        return _parse_json(response.choices[0].message.content)
    except Exception as e:
        log(f"  Judge failed: {e} — defaulting to approved")
        return {'approved': True, 'rejection_reason': '', 'revised_ideal_patient_type': ''}


def _build_user_message(clinic: dict, website_text: str) -> str:
    lines = [
        f"Clinic name: {clinic.get('clinic_name', '')}",
        f"Location: {clinic.get('location', '')}",
    ]

    rating = clinic.get('rating')
    reviews = clinic.get('review_count')
    if rating:
        lines.append(f"Doctify rating: {rating} ({reviews} reviews)")

    # Specialty tags and specialist count from the listing card
    tags = clinic.get('specialty_tags', '')
    if isinstance(tags, list):
        tags = '; '.join(tags)
    if tags:
        lines.append(f"Specialty tags (from listing): {tags}")

    count = clinic.get('specialist_count')
    if count:
        lines.append(f"Specialist count (from listing): {count}")

    about = clinic.get('doctify_about', '')
    if about:
        lines.append(f"\nDoctify profile description:\n{about}")

    if website_text:
        lines.append(f"\nWebsite content:\n{website_text}")

    if not about and not website_text:
        lines.append("\nNo description or website content available.")

    return '\n'.join(lines)
