"""Environment configuration for the MCP server."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_SERVER_ROOT = Path(__file__).resolve().parents[1]
_MONOREPO_ROOT = Path(__file__).resolve().parents[2]
# Monorepo: IntelligenceOS root (templates/, marketing-pipeline/). Standalone: mcp-server / mcp_social root.
REPO_ROOT = (
    _MONOREPO_ROOT
    if (_MONOREPO_ROOT / "marketing-pipeline").is_dir()
    else _SERVER_ROOT
)

load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(REPO_ROOT / ".env")
load_dotenv(_SERVER_ROOT / ".env.local")
load_dotenv(_SERVER_ROOT / ".env")


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
OPENROUTER_CHAT_MODEL = _getenv(
    "OPENROUTER_CHAT_MODEL", "MODEL_MCP", default="anthropic/claude-sonnet-4"
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
MCP_ALLOWED_HOSTS = [
    host.strip()
    for host in _getenv("MCP_ALLOWED_HOSTS").split(",")
    if host.strip()
]
MCP_DNS_REBINDING_PROTECTION = _getenv(
    "MCP_DNS_REBINDING_PROTECTION", default="true"
).strip().lower() not in {"0", "false", "no", "off"}
MCP_MAX_SENSITIVITY = _getenv("MCP_MAX_SENSITIVITY", default="confidential")
HOST = _getenv("MCP_HOST", default="0.0.0.0")
PORT = int(_getenv("MCP_PORT", "8000"))
GMAIL_CLIENT_ID = _getenv("GMAIL_CLIENT_ID")
GMAIL_CLIENT_SECRET = _getenv("GMAIL_CLIENT_SECRET")
GMAIL_REFRESH_TOKEN = _getenv("GMAIL_REFRESH_TOKEN")
