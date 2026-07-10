"""OpenRouter embedding client."""

from __future__ import annotations

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
) -> str:
    client = _get_client()
    response = client.chat.completions.create(
        model=model or config.MODEL_COMPONENTS,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
    )
    return (response.choices[0].message.content or "").strip()
