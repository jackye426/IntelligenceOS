"""Vision LLM OCR via OpenRouter (TikTok frame hooks)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx

from marketing_pipeline import config


def image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".webp": "image/webp",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(suffix, "image/jpeg")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def ocr_image(path: Path, *, model: str | None = None) -> dict:
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY must be set for vision OCR")

    model_id = model or config.MODEL_OCR
    data_url = image_to_data_url(path)
    payload = {
        "model": model_id,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "Extract on-screen text from TikTok video frames. Return JSON only.",
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "OCR this TikTok video frame. Extract ALL visible hook/on-screen text.\n"
                            "Ignore watermarks like @username unless it is the main message.\n"
                            'Return JSON: {"text": "...", "confidence": 0.0}\n'
                            "Confidence is 0.0-1.0. Empty string if no readable text."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=60.0)) as client:
        response = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    content = data["choices"][0]["message"]["content"]
    return json.loads(content)
