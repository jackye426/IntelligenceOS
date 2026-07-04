"""OpenRouter embedding client."""

from __future__ import annotations

import logging
import time

from openai import OpenAI

logger = logging.getLogger(__name__)

from ingestion_pipeline import config

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is not None:
        return _client
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY must be set in .env.local")
    _client = OpenAI(
        api_key=config.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
    )
    return _client


def embed_text(text: str, *, attempts: int = 3) -> list[float]:
    """Embed with retry — long import runs must survive transient network blips."""
    client = _get_client()
    for attempt in range(1, attempts + 1):
        try:
            response = client.embeddings.create(
                model=config.OPENROUTER_EMBEDDING_MODEL,
                input=text[:8000],
            )
            vector = response.data[0].embedding
            if not vector:
                raise RuntimeError("OpenRouter returned an empty embedding")
            return vector
        except Exception as exc:
            if attempt == attempts:
                raise
            delay = 2 ** attempt
            logger.warning("embed_text attempt %d failed (%s); retrying in %ds",
                           attempt, exc, delay)
            time.sleep(delay)
    raise RuntimeError("unreachable")
