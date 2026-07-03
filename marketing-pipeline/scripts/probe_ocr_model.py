"""Probe OpenRouter vision models for OCR."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx

from marketing_pipeline import config

frame = next(Path("marketing-pipeline/tiktok/data/ocr/frames").rglob("frame_0.0s.jpg"))
enc = base64.b64encode(frame.read_bytes()).decode()
url = f"data:image/jpeg;base64,{enc}"

models = [
    "openai/gpt-4o-mini",
    "google/gemini-2.5-flash-preview",
    "google/gemini-2.0-flash-001",
    "google/gemini-3-flash-preview",
]

for model in models:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": 'Return JSON {"text":"...","confidence":0.9} with visible on-screen text only.',
                    },
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }
        ],
        "response_format": {"type": "json_object"},
    }
    r = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://docmap.co",
            "X-Title": "DocMap Intelligence OS",
        },
        json=payload,
        timeout=60,
    )
    print(model, r.status_code)
    print(r.text[:300])
    print("---")
