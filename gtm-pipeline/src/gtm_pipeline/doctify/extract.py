"""Playwright extract for Doctify practice pages (LOCKED selectors).

Selectors (do not change without a fixture re-validation):
  - Count label:  [data-testid="specialist-link"]  → "N specialists" (COUNT, not person links)
  - Cards:        [data-testid="specialist-card"]
  - Name/URL:     [data-testid="specialist-name"]
  - Specialty:    [data-testid="specialist-specialty"]

Also dismiss cookie CMP (AGREE) and click "Load more specialists" until
card count == listed_specialist_count.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

from gtm_pipeline.scoring import (
    classify_visible_clinic_size,
    compute_founder_score,
    scan_leadership,
)
from gtm_pipeline.shared.address import normalise_postcode, parse_address
from gtm_pipeline.shared.provenance import evidence_item, make_provenance

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


@dataclass
class SpecialistCard:
    name: str
    profile_url: str = ""
    specialty: str = ""


@dataclass
class DoctifyPracticeExtract:
    doctify_url: str
    clinic_name: str = ""
    bio: str = ""
    address: str = ""
    postcode: str = ""
    specialties: list[str] = field(default_factory=list)
    website_url: str = ""
    email: str = ""
    phone: str = ""
    listed_specialist_count: int | None = None
    specialists: list[SpecialistCard] = field(default_factory=list)
    visible_clinic_size: str = "unknown"
    leadership_keywords: list[str] = field(default_factory=list)
    leadership_role: str | None = None
    founder_score: int = 0
    structure: str = "unknown"
    evidence: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    raw_next_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Keep payloads lean for CLI / upsert — drop huge NEXT blobs by default.
        d.pop("raw_next_data", None)
        return d


async def _dismiss_cookies(page) -> None:
    """Dismiss OneTrust / CMP; prefer AGREE / Accept."""
    candidates = [
        page.get_by_role("button", name=re.compile(r"^\s*agree\s*$", re.I)),
        page.get_by_role("button", name=re.compile(r"accept\s*all", re.I)),
        page.locator("button").filter(has_text=re.compile(r"agree|accept|got it|allow", re.I)).first,
        page.locator("#onetrust-accept-btn-handler"),
    ]
    for loc in candidates:
        try:
            await loc.click(timeout=2500)
            await asyncio.sleep(0.4)
            return
        except Exception:
            continue


async def _read_listed_count(page) -> int | None:
    """Read specialist COUNT from [data-testid=specialist-link] text."""
    try:
        loc = page.locator('[data-testid="specialist-link"]').first
        text = (await loc.inner_text(timeout=5000)).strip()
    except Exception:
        return None
    m = re.search(r"(\d+)\s*specialist", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None


async def _load_all_specialists(page, listed_count: int | None, max_clicks: int = 30) -> int:
    """Click 'Load more specialists' until cards catch up to listed count."""
    cards = page.locator('[data-testid="specialist-card"]')
    for _ in range(max_clicks):
        count = await cards.count()
        if listed_count is not None and count >= listed_count:
            return count
        btn = page.get_by_role(
            "button", name=re.compile(r"load\s+more\s+specialists?", re.I)
        )
        try:
            if not await btn.is_visible(timeout=1500):
                break
            await btn.click(timeout=3000)
            await asyncio.sleep(0.8)
        except Exception:
            # Fallback text locator
            alt = page.locator("button, a").filter(
                has_text=re.compile(r"load\s+more\s+specialists?", re.I)
            ).first
            try:
                await alt.click(timeout=2000)
                await asyncio.sleep(0.8)
            except Exception:
                break
    return await cards.count()


async def _extract_specialist_cards(page) -> list[SpecialistCard]:
    cards_loc = page.locator('[data-testid="specialist-card"]')
    n = await cards_loc.count()
    out: list[SpecialistCard] = []
    for i in range(n):
        card = cards_loc.nth(i)
        name = ""
        profile_url = ""
        specialty = ""
        try:
            name_el = card.locator('[data-testid="specialist-name"]').first
            name = (await name_el.inner_text()).strip()
            href = await name_el.get_attribute("href")
            if href:
                profile_url = urljoin("https://www.doctify.com", href)
            elif await name_el.evaluate("el => el.tagName"):
                # name may wrap an <a>
                link = card.locator('a[href*="/specialist/"]').first
                href2 = await link.get_attribute("href")
                if href2:
                    profile_url = urljoin("https://www.doctify.com", href2)
        except Exception:
            pass
        try:
            specialty = (
                await card.locator('[data-testid="specialist-specialty"]').first.inner_text()
            ).strip()
        except Exception:
            pass
        if name:
            out.append(SpecialistCard(name=name, profile_url=profile_url, specialty=specialty))
    return out


def _practice_from_next_data(html: str) -> dict[str, Any]:
    """Best-effort structured fields from __NEXT_DATA__."""
    out: dict[str, Any] = {}
    m = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html,
        re.S,
    )
    if not m:
        return out
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return out

    out["_raw"] = data
    props = data.get("props", {}).get("pageProps", {})
    practice = (
        props.get("practice")
        or props.get("clinic")
        or props.get("profile")
        or props.get("data")
        or {}
    )
    if not isinstance(practice, dict):
        practice = {}

    def _str(val: Any) -> str:
        if isinstance(val, dict):
            return str(val.get("en") or val.get("name") or "").strip()
        return str(val or "").strip()

    name = _str(practice.get("name") or practice.get("fullName") or practice.get("title"))
    if name:
        out["clinic_name"] = name

    about = _str(practice.get("about") or practice.get("description") or practice.get("bio"))
    if about:
        out["bio"] = about

    address = practice.get("address") or practice.get("location") or {}
    if isinstance(address, dict):
        parts = [
            address.get("line1") or address.get("street"),
            address.get("line2"),
            address.get("city") or address.get("town"),
            address.get("postcode") or address.get("postalCode"),
        ]
        out["address"] = ", ".join(str(p) for p in parts if p)
        out["postcode"] = normalise_postcode(
            address.get("postcode") or address.get("postalCode") or out["address"]
        )
    elif isinstance(address, str):
        out["address"] = address
        out["postcode"] = normalise_postcode(address)

    for key in ("websiteUrl", "website", "externalUrl", "practiceWebsite", "siteUrl"):
        val = practice.get(key)
        if isinstance(val, str) and val.startswith("http") and "doctify" not in val:
            out["website_url"] = val
            break

    for key in ("email", "contactEmail", "enquiryEmail", "practiceEmail"):
        val = practice.get(key)
        if isinstance(val, str) and EMAIL_RE.match(val) and "doctify" not in val:
            out["email"] = val
            break

    for key in ("phone", "telephone", "phoneNumber", "contactPhone"):
        val = practice.get(key)
        if isinstance(val, str) and len(re.sub(r"\D", "", val)) >= 7:
            out["phone"] = val.strip()
            break

    specs = practice.get("specialties") or practice.get("specialities") or practice.get("tags") or []
    if isinstance(specs, list):
        cleaned = []
        for s in specs:
            if isinstance(s, dict):
                cleaned.append(_str(s.get("name") or s.get("title") or s))
            else:
                cleaned.append(_str(s))
        out["specialties"] = [c for c in cleaned if c]

    return out


def _clinic_name_from_dom(html: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
    if not m:
        return ""
    return re.sub(r"<[^>]+>", "", m.group(1)).strip()


def _bio_from_dom(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    paras: list[str] = []
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        if len(text) < 60:
            continue
        low = text.lower()
        if any(k in low for k in ("cookie", "privacy", "verified patient", "write a review")):
            continue
        paras.append(text)
        if len(paras) >= 5:
            break
    return "\n\n".join(paras)


async def extract_practice(url: str, *, headless: bool = True) -> DoctifyPracticeExtract:
    """Live Playwright extract of a Doctify practice page."""
    from playwright.async_api import async_playwright

    # Normalise to specialists tab when possible
    parsed = urlparse(url)
    if "#specialists" not in url and "/practice/" in parsed.path:
        url = url.split("#")[0] + "#specialists"

    result = DoctifyPracticeExtract(
        doctify_url=url.split("#")[0],
        provenance=make_provenance(
            source="doctify",
            source_url=url,
            lane="doctify",
            extractor="playwright_practice_v1",
        ),
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        ctx = await browser.new_context(user_agent=_UA, viewport={"width": 1280, "height": 900})
        page = await ctx.new_page()
        try:
            try:
                await page.goto(url, wait_until="networkidle", timeout=45000)
            except Exception:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(2)

            await _dismiss_cookies(page)
            # Ensure specialists section is in view / hash applied
            try:
                await page.locator('[data-testid="specialist-link"]').first.click(timeout=3000)
                await asyncio.sleep(0.5)
            except Exception:
                pass

            listed = await _read_listed_count(page)
            result.listed_specialist_count = listed
            await _load_all_specialists(page, listed)
            result.specialists = await _extract_specialist_cards(page)

            html = await page.content()
            next_fields = _practice_from_next_data(html)
            result.raw_next_data = next_fields.pop("_raw", {}) if "_raw" in next_fields else {}

            result.clinic_name = next_fields.get("clinic_name") or _clinic_name_from_dom(html)
            result.bio = next_fields.get("bio") or _bio_from_dom(html)
            result.address = next_fields.get("address") or ""
            result.postcode = next_fields.get("postcode") or normalise_postcode(result.address)
            if not result.postcode and result.address:
                result.postcode = parse_address(result.address).postcode
            result.website_url = next_fields.get("website_url") or ""
            result.email = next_fields.get("email") or ""
            result.phone = next_fields.get("phone") or ""
            result.specialties = next_fields.get("specialties") or []

            # Prefer observed card count when listed count missing
            count = result.listed_specialist_count
            if count is None:
                count = len(result.specialists)
                result.listed_specialist_count = count
            result.visible_clinic_size = classify_visible_clinic_size(count)

            leadership = scan_leadership(result.bio)
            if leadership:
                result.leadership_keywords = leadership.keywords
                result.leadership_role = leadership.role
                result.evidence.append(
                    evidence_item(
                        kind="leadership_bio",
                        value={"role": leadership.role, "snippets": leadership.snippets},
                        source="doctify",
                        source_url=result.doctify_url,
                    )
                )

            score, structure = compute_founder_score(
                leadership=leadership,
                visible_clinic_size=result.visible_clinic_size,
                specialist_count=count,
            )
            result.founder_score = score
            result.structure = structure

            result.evidence.append(
                evidence_item(
                    kind="specialist_count",
                    value={
                        "listed": result.listed_specialist_count,
                        "cards": len(result.specialists),
                        "size": result.visible_clinic_size,
                    },
                    source="doctify",
                    source_url=result.doctify_url,
                )
            )
        finally:
            await ctx.close()
            await browser.close()

    return result


def extract_practice_sync(url: str, *, headless: bool = True) -> DoctifyPracticeExtract:
    return asyncio.run(extract_practice(url, headless=headless))


def parse_specialists_from_html(html: str, *, doctify_url: str = "") -> DoctifyPracticeExtract:
    """Offline/fixture path using LOCKED testids via BeautifulSoup."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    result = DoctifyPracticeExtract(
        doctify_url=doctify_url,
        provenance=make_provenance(
            source="doctify",
            source_url=doctify_url or None,
            lane="doctify",
            extractor="html_fixture_v1",
        ),
    )

    link = soup.select_one('[data-testid="specialist-link"]')
    if link:
        text = link.get_text(" ", strip=True)
        m = re.search(r"(\d+)\s*specialist", text, re.I) or re.search(r"(\d+)", text)
        if m:
            result.listed_specialist_count = int(m.group(1))

    for card in soup.select('[data-testid="specialist-card"]'):
        name_el = card.select_one('[data-testid="specialist-name"]')
        spec_el = card.select_one('[data-testid="specialist-specialty"]')
        name = name_el.get_text(" ", strip=True) if name_el else ""
        href = ""
        if name_el and name_el.name == "a":
            href = name_el.get("href") or ""
        elif name_el:
            a = name_el.find("a", href=True) or card.find("a", href=re.compile(r"/specialist/"))
            if a:
                href = a.get("href") or ""
        specialty = spec_el.get_text(" ", strip=True) if spec_el else ""
        if name:
            result.specialists.append(
                SpecialistCard(
                    name=name,
                    profile_url=urljoin("https://www.doctify.com", href) if href else "",
                    specialty=specialty,
                )
            )

    next_fields = _practice_from_next_data(html)
    next_fields.pop("_raw", None)
    result.clinic_name = next_fields.get("clinic_name") or _clinic_name_from_dom(html)
    result.bio = next_fields.get("bio") or _bio_from_dom(html)
    result.address = next_fields.get("address") or ""
    result.postcode = next_fields.get("postcode") or normalise_postcode(result.address)
    result.website_url = next_fields.get("website_url") or ""
    result.email = next_fields.get("email") or ""
    result.phone = next_fields.get("phone") or ""
    result.specialties = next_fields.get("specialties") or []

    count = result.listed_specialist_count or len(result.specialists)
    result.listed_specialist_count = count
    result.visible_clinic_size = classify_visible_clinic_size(count)
    leadership = scan_leadership(result.bio)
    if leadership:
        result.leadership_keywords = leadership.keywords
        result.leadership_role = leadership.role
    score, structure = compute_founder_score(
        leadership=leadership,
        visible_clinic_size=result.visible_clinic_size,
        specialist_count=count,
    )
    result.founder_score = score
    result.structure = structure
    return result
