"""Supabase client factory for gtm-pipeline."""

from __future__ import annotations

from supabase import Client, create_client

from gtm_pipeline import config

_client: Client | None = None


def supabase_configured() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_ROLE_KEY)


def get_client() -> Client:
    global _client
    if _client is not None:
        return _client

    if not supabase_configured():
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env.local / .env"
        )

    _client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
    return _client
