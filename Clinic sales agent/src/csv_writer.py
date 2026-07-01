import csv
import os
import pandas as pd

import sys
sys.path.insert(0, os.path.dirname(__file__))
from utils import log

COLUMNS = [
    'clinic_name',
    'doctify_profile_url',
    'website_url',
    'location',
    'specialty_tags',
    'specialist_count',
    'review_count',
    'contact_email',
    'phone',
    'doctify_about',
    'cqc_location_id',
    'cqc_registered_manager',
    'cqc_nominated_individual',
    'cqc_match_confidence',
    'decision_maker_email',
    'decision_maker_name_matched',
    'decision_maker_email_source',
    'decision_maker_email_confidence',
    'decision_maker_email_verified',
    'doctify_email',
    'doctify_specialist_slug',
    'clinic_summary',
    'relevant_services',
    'key_people',
    'code_score',
    'salutation_name',
    'judge_approved',
    'judge_reason',
    'auto_send_eligible',
    'gmail_draft_id',
    'fit_score',
    'fit_reason',
    'best_sales_angle',
    'possible_objection',
    'filter_reason',
    'tailored_line',
    'suggested_subject',
    'suggested_email_body',
    'status',
    'error',
    'email_sent_date',
    'email_thread_id',
    'followup_draft_id',
    'followup_status',
]


def _flatten(val) -> str:
    if val is None:
        return ''
    if isinstance(val, list):
        val = '; '.join(str(x) for x in val)
    # Replace embedded newlines so CSV rows stay single-line
    return str(val).replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')


def _safe_save(df: pd.DataFrame, output_path: str):
    """Write to a .tmp file then atomically rename — survives kill mid-write."""
    tmp = output_path + '.tmp'
    df.to_csv(tmp, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_ALL)
    os.replace(tmp, output_path)  # atomic on same filesystem


def write_results(clinics: list, output_path: str):
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    rows = [{col: _flatten(c.get(col)) for col in COLUMNS} for c in clinics]
    df = pd.DataFrame(rows, columns=COLUMNS)
    _safe_save(df, output_path)
    log(f"Saved {len(rows)} rows -> {output_path}")


def append_result(clinic: dict, output_path: str):
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    row = {col: _flatten(clinic.get(col)) for col in COLUMNS}
    df = pd.DataFrame([row], columns=COLUMNS)
    write_header = not os.path.exists(output_path)
    df.to_csv(output_path, mode='a', header=write_header, index=False,
              encoding='utf-8-sig', quoting=csv.QUOTE_ALL)
