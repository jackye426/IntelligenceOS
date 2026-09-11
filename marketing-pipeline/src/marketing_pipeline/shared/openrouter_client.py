"""OpenRouter embedding client."""

from __future__ import annotations

import time

from openai import OpenAI

from marketing_pipeline import config

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


def embed_text(text: str) -> list[float]:
    client = _get_client()
    response = client.embeddings.create(
        model=config.OPENROUTER_EMBEDDING_MODEL,
        input=text[:8000],
    )
    vector = response.data[0].embedding
    if not vector:
        raise RuntimeError("OpenRouter returned an empty embedding")
    return vector


def chat_completion(
    *,
    system: str,
    user: str,
    model: str | None = None,
    max_tokens: int = 2000,
    attempts: int = 3,
) -> str:
    """Chat completion that retries empty responses.

    A provider returning empty content is common under load, and it surfaces
    downstream as `json.loads("")` failing with "Expecting value: line 1
    column 1" — an error that looks like a parsing bug rather than a missing
    response. Roughly a third of one batch failed this way before the retry.
    """
    client = _get_client()
    last_finish = None
    for attempt in range(1, attempts + 1):
        response = client.chat.completions.create(
            model=model or config.MODEL_COMPONENTS,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
        )
        choice = response.choices[0] if response.choices else None
        content = ((choice.message.content if choice else None) or "").strip()
        last_finish = getattr(choice, "finish_reason", None) if choice else None
        if content:
            return content
        if attempt < attempts:
            time.sleep(min(2**attempt, 20))

    raise RuntimeError(
        f"Model {model or config.MODEL_COMPONENTS} returned empty content "
        f"{attempts} times (last finish_reason={last_finish!r})."
    )
