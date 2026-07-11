"""Environment configuration for Relationship Desk."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(REPO_ROOT / ".env")


def _getenv(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


SUPABASE_URL = _getenv("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = _getenv("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY")
PRACTITIONERS_TABLE = _getenv(
    "SUPABASE_PRACTITIONERS_TABLE",
    default="integrated_practitioner_with_phin",
)

AUTH_TOKEN = _getenv("RELATIONSHIP_DESK_AUTH_TOKEN", "MCP_AUTH_TOKEN")
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in _getenv("RELATIONSHIP_DESK_ALLOWED_ORIGINS").split(",")
    if origin.strip()
]
ALLOWED_HOSTS = [
    host.strip()
    for host in _getenv("RELATIONSHIP_DESK_ALLOWED_HOSTS").split(",")
    if host.strip()
]
DNS_REBINDING_PROTECTION = _getenv(
    "RELATIONSHIP_DESK_DNS_REBINDING_PROTECTION",
    default="true",
).strip().lower() not in {"0", "false", "no", "off"}

HOST = _getenv("RELATIONSHIP_DESK_HOST", default="0.0.0.0")
PORT = int(_getenv("RELATIONSHIP_DESK_PORT", default="8000"))

DESK_MODE = _getenv("RELATIONSHIP_DESK_MODE", default="draft_only").strip().lower()
DEFAULT_CHASE_DAYS = int(_getenv("RELATIONSHIP_DEFAULT_CHASE_DAYS", default="5"))
MAX_AUTO_SEND_PER_RUN = int(_getenv("RELATIONSHIP_MAX_AUTO_SEND_PER_RUN", default="10"))
MAX_THREAD_MESSAGES = int(_getenv("RELATIONSHIP_MAX_THREAD_MESSAGES", default="20"))

GMAIL_CLIENT_ID = _getenv("RELATIONSHIP_GMAIL_CLIENT_ID", "GMAIL_CLIENT_ID")
GMAIL_CLIENT_SECRET = _getenv(
    "RELATIONSHIP_GMAIL_CLIENT_SECRET",
    "GMAIL_CLIENT_SECRET",
)
GMAIL_REFRESH_TOKEN = _getenv(
    "RELATIONSHIP_GMAIL_REFRESH_TOKEN",
    "GMAIL_REFRESH_TOKEN",
)
GMAIL_ACCOUNT_EMAIL = _getenv("RELATIONSHIP_GMAIL_ACCOUNT_EMAIL")


def bool_env(name: str, default: bool = False) -> bool:
    raw = _getenv(name, default="true" if default else "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}
