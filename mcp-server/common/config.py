"""Environment configuration for the MCP server."""

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
OPENROUTER_API_KEY = _getenv("OPENROUTER_API_KEY")
OPENROUTER_EMBEDDING_MODEL = _getenv(
    "OPENROUTER_EMBEDDING_MODEL", default="openai/text-embedding-3-small"
)
PRACTITIONERS_TABLE = _getenv(
    "SUPABASE_PRACTITIONERS_TABLE", default="integrated_practitioner_with_phin"
)
MCP_AUTH_TOKEN = _getenv("MCP_AUTH_TOKEN")
MCP_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in _getenv("MCP_ALLOWED_ORIGINS").split(",")
    if origin.strip()
]
MCP_MAX_SENSITIVITY = _getenv("MCP_MAX_SENSITIVITY", default="confidential")
HOST = _getenv("MCP_HOST", default="0.0.0.0")
PORT = int(_getenv("MCP_PORT", "8000"))
