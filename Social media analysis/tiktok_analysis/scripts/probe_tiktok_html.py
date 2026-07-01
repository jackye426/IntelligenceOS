"""Probe TikTok page embedded state for comment structures."""
import json
import re
import urllib.request

URL = "https://www.tiktok.com/@docmap/video/7630900114982210838"

req = urllib.request.Request(
    URL, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
)
html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="replace")
m = re.search(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>([^<]+)</script>', html
)
if not m:
    raise SystemExit("no embedded state")
data = json.loads(m.group(1))


def find_keys(obj, needle, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}"
            if needle in k.lower():
                yield p, type(v).__name__
            yield from find_keys(v, needle, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:50]):
            yield from find_keys(v, needle, f"{path}[{i}]")


hits = list(find_keys(data, "comment"))[:40]
for h in hits:
    print(h)
