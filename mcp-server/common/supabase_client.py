"""Supabase client factory."""

from __future__ import annotations

from supabase import Client, create_client

from . import config

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is not None:
        return _client

    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured"
        )

    _client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
    return _client
