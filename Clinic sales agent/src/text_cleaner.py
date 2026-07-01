import re
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from config import MAX_TEXT_CHARS


def clean_and_cap(pages: list) -> str:
    parts = []
    for page in pages:
        url = page.get('url', '')
        title = page.get('title', '')
        text = page.get('text', '')

        if not text or len(text.strip()) < 50:
            continue

        cleaned = _clean(text)
        if cleaned:
            header = f"--- {title or url} ---\n"
            parts.append(header + cleaned)

    combined = '\n\n'.join(parts)

    if len(combined) > MAX_TEXT_CHARS:
        combined = combined[:MAX_TEXT_CHARS] + '\n...[truncated]'

    return combined


def _clean(text: str) -> str:
    text = re.sub(r'\n{3,}', '\n\n', text)

    lines = [l for l in text.splitlines() if len(l.strip()) > 10 or l.strip() == '']
    text = '\n'.join(lines)

    boilerplate = [
        r'cookie(s)? policy',
        r'accept all cookies',
        r'we use cookies',
        r'privacy policy',
        r'terms (and|&) conditions',
        r'all rights reserved',
        r'©\s*\d{4}',
        r'follow us on',
        r'subscribe to our newsletter',
    ]
    for pattern in boilerplate:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)

    return text.strip()
