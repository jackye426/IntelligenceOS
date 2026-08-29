"""Configuration for Spire appointment monitor."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# Prefer package .env, then repo-root .env.local / .env
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env.local")
load_dotenv(ROOT.parent / ".env")


@dataclass(frozen=True)
class Consultant:
    name: str
    consultant_id: str
    profile_url: str


# Locked Cardiff roster (validated 2026-08-29)
DEFAULT_CONSULTANTS: tuple[Consultant, ...] = (
    Consultant(
        name="Mr Simon Phillips",
        consultant_id="C4069414",
        profile_url="https://www.spirehealthcare.com/consultant-profiles/mr-simon-phillips-c4069414/",
    ),
    Consultant(
        name="Miss Julie Cornish",
        consultant_id="C6031568",
        profile_url="https://www.spirehealthcare.com/spire-cardiff-hospital/consultants/julie-cornish-c6031568/",
    ),
    Consultant(
        name="Mr Faris Soliman",
        consultant_id="C7082057",
        profile_url="https://www.spirehealthcare.com/spire-cardiff-hospital/consultants/mr-faris-soliman-c7082057/",
    ),
)

API_BASE = "https://appointments.spirehealthcare.com/Umbraco/Api"
SOURCE_SYSTEM = "spire_monitor"
SCRAPE_TIMES_LONDON = ("07:00", "13:00", "19:00")
T_WINDOWS_DAYS = (21, 14, 7, 3, 2)  # 2 = T-48h
MAX_LOOKAHEAD_MONTHS = int(os.getenv("SPIRE_LOOKAHEAD_MONTHS", "3"))
HTTP_RETRIES = int(os.getenv("SPIRE_HTTP_RETRIES", "3"))
HTTP_TIMEOUT_S = float(os.getenv("SPIRE_HTTP_TIMEOUT", "30"))
REQUEST_DELAY_S = float(os.getenv("SPIRE_REQUEST_DELAY", "0.4"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_ROLE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    or os.getenv("SUPABASE_SERVICE_KEY", "").strip()
)
DRY_RUN = os.getenv("SPIRE_DRY_RUN", "").lower() in {"1", "true", "yes"}


def load_consultants() -> list[Consultant]:
    """Default roster, or SPIRE_CONSULTANTS JSON override."""
    raw = os.getenv("SPIRE_CONSULTANTS", "").strip()
    if not raw:
        return list(DEFAULT_CONSULTANTS)
    data = json.loads(raw)
    out: list[Consultant] = []
    for item in data:
        out.append(
            Consultant(
                name=str(item["name"]),
                consultant_id=str(item["consultant_id"]).upper(),
                profile_url=str(item["profile_url"]),
            )
        )
    return out
