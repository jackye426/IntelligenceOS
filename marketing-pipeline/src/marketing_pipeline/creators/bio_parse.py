"""Deterministic bio extraction. LLM is not used here."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
GMC_RE = re.compile(r"\b(\d{7})\b")
URL_RE = re.compile(r"https?://[^\s)>\]]+", re.I)
HANDLE_RE = re.compile(
    r"(?:instagram|ig|youtube|yt|twitter|x|linkedin)\s*[:/]+@?([A-Za-z0-9._]+)",
    re.I,
)
AT_HANDLE_RE = re.compile(r"(?:^|\s)@([A-Za-z0-9._]{2,})")

UK_CITIES = (
    "london",
    "manchester",
    "birmingham",
    "leeds",
    "glasgow",
    "edinburgh",
    "cardiff",
    "belfast",
    "bristol",
    "liverpool",
    "newcastle",
    "sheffield",
    "nottingham",
    "oxford",
    "cambridge",
    "harley street",
)

BOOKING_HOSTS = (
    "doctify.com",
    "topdoctors.co.uk",
    "spirehealthcare.com",
    "nuffieldhealth.com",
    "hcahealthcare.co.uk",
    "theprivateclinic.co.uk",
)
LINKTREE_HOSTS = ("linktr.ee", "beacons.ai", "stan.store", "linkin.bio")
SOCIAL_HOSTS = (
    "instagram.com",
    "youtube.com",
    "youtu.be",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "tiktok.com",
    "facebook.com",
)


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except ValueError:
        return ""


def classify_url(url: str) -> str:
    host = _host(url)
    if any(host.endswith(h) or host == h for h in BOOKING_HOSTS):
        return "booking_platform"
    if any(host.endswith(h) or host == h for h in LINKTREE_HOSTS):
        return "linktree_like"
    if any(host.endswith(h) or host == h for h in SOCIAL_HOSTS):
        return "social"
    if host:
        return "own_site"
    return "other"


def parse_bio(nickname: str | None, bio: str | None, bio_link: str | None = None) -> dict[str, Any]:
    text = " ".join(p for p in (nickname, bio, bio_link) if p)
    emails = sorted({m.group(0).lower() for m in EMAIL_RE.finditer(text)})
    urls = []
    seen = set()
    for raw in [bio_link or "", *URL_RE.findall(bio or "")]:
        url = raw.strip().rstrip(".,)")
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append({"url": url, "class": classify_url(url)})

    handles: dict[str, str] = {}
    for m in HANDLE_RE.finditer(text):
        handles[m.group(0).split(":")[0].lower()[:2]] = m.group(1)

    gmc = None
    gm = GMC_RE.search(text)
    if gm:
        gmc = gm.group(1)

    geo_signals: list[dict[str, Any]] = []
    lower = text.lower()
    if ".co.uk" in lower or any(h.endswith(".co.uk") for h in (_host(u["url"]) for u in urls)):
        geo_signals.append({"signal": "co_uk", "weight": 0.9, "geo": "GB"})
    if gmc or "mrcgp" in lower or "harley street" in lower:
        geo_signals.append({"signal": "uk_credential", "weight": 0.8, "geo": "GB"})
    if any(city in lower for city in UK_CITIES):
        geo_signals.append({"signal": "uk_city", "weight": 0.6, "geo": "GB"})
    if "board-certified" in lower or "board certified" in lower:
        geo_signals.append({"signal": "us_board", "weight": 0.7, "geo": "US"})

    geo_country = None
    geo_confidence = None
    if geo_signals:
        best = max(geo_signals, key=lambda s: s["weight"])
        geo_country = best["geo"]
        geo_confidence = best["weight"]

    return {
        "bio_emails": emails,
        "bio_links": urls,
        "bio_handles": handles,
        "gmc_number_in_bio": gmc,
        "geo_signals": geo_signals,
        "geo_country": geo_country,
        "geo_confidence": geo_confidence,
    }
