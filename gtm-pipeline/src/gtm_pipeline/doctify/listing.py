"""Doctify listing discovery (practice URLs only) — gtm-pipeline, no OG scraper.

Listing pages only. Practice enrichment is ``doctify.extract``.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from playwright.async_api import async_playwright

from gtm_pipeline import config

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_SCOPE = config.DOCTIFY_SCOPE_CSV


@dataclass
class ListingStub:
    clinic_name: str = ""
    doctify_url: str = ""
    location: str = ""
    specialty_tags: list[str] = field(default_factory=list)
    specialist_count: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_page_url(base_url: str, page_num: int) -> str:
    parsed = urlparse(base_url)
    path = re.sub(r"/page-\d+$", "", parsed.path.rstrip("/"))
    if page_num > 1:
        path = f"{path}/page-{page_num}"
    return urlunparse(parsed._replace(path=path))


def load_scope_csv(path: Path | str) -> list[dict[str, Any]]:
    path = Path(path)
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = (row.get("url") or "").strip()
            if not url:
                continue
            pages = int(row.get("pages") or 1)
            rows.append({"url": url, "pages": max(1, pages)})
    return rows


def _en(val: Any) -> str:
    if isinstance(val, dict):
        return str(val.get("en") or next(iter(val.values()), "") or "").strip()
    return str(val).strip() if val else ""


def _get(obj: dict, *keys: str) -> Any:
    for k in keys:
        if k in obj:
            return obj[k]
        for actual in obj:
            if actual.lower() == k.lower():
                return obj[actual]
    return None


def _looks_like_clinic_list(lst: list) -> bool:
    if not lst or len(lst) < 2 or not isinstance(lst[0], dict) or len(lst[0]) < 8:
        return False
    sample = lst[0]
    name_val = sample.get("name") or sample.get("title") or sample.get("displayName")
    if name_val is not None and not isinstance(name_val, str):
        if not (isinstance(name_val, dict) and isinstance(name_val.get("en"), str)):
            return False
    strong = {
        "address",
        "averageRating",
        "reviewsTotal",
        "externalId",
        "distance",
        "rating",
        "reviewCount",
        "location",
        "profileUrl",
        "profile_url",
        "latitude",
        "longitude",
        "physicalLocation",
    }
    return bool(strong & set(sample.keys()))


def _normalise_clinic(item: dict) -> ListingStub | None:
    name = _en(_get(item, "name", "title", "displayName", "practiceName") or "")
    slug = _get(item, "slug", "urlSlug", "url_slug") or ""
    profile = _get(item, "profileUrl", "profile_url", "url", "href", "link", "path") or ""
    if slug and not profile:
        profile = f"https://www.doctify.com/uk/practice/{slug}"
    elif profile and not str(profile).startswith("http"):
        profile = f"https://www.doctify.com{profile}"
    profile = str(profile).strip()
    if "/practice/" not in profile:
        return None

    loc = _get(item, "location", "address", "practiceAddress") or {}
    if isinstance(loc, dict):
        location = ", ".join(
            filter(
                None,
                [_en(loc.get("city", "")), _en(loc.get("area", "")), _en(loc.get("postcode", ""))],
            )
        )
    else:
        location = str(loc) if loc else ""

    tags: list[str] = []
    keywords = item.get("keywords", [])
    if isinstance(keywords, list):
        for kw in keywords:
            if isinstance(kw, dict) and kw.get("keywordType") == "specialty":
                tag = _en(kw.get("name", ""))
                if tag:
                    tags.append(tag)

    raw_specialists = _get(
        item,
        "specialists",
        "practitionerCount",
        "specialistCount",
        "doctorCount",
        "totalPractitioners",
    )
    if isinstance(raw_specialists, list):
        count = len(raw_specialists) if raw_specialists else None
    else:
        try:
            count = int(raw_specialists) if raw_specialists is not None else None
        except (TypeError, ValueError):
            count = None

    return ListingStub(
        clinic_name=name,
        doctify_url=profile.split("#")[0].rstrip("/"),
        location=location.strip(),
        specialty_tags=tags,
        specialist_count=count,
    )


def _extract_clinics_from_json(data: Any) -> list[ListingStub]:
    def walk(obj: Any, depth: int = 0) -> list[ListingStub]:
        if depth > 6:
            return []
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            if _looks_like_clinic_list(obj):
                out: list[ListingStub] = []
                for item in obj:
                    if isinstance(item, dict):
                        stub = _normalise_clinic(item)
                        if stub:
                            out.append(stub)
                return out
        if isinstance(obj, dict):
            for val in obj.values():
                found = walk(val, depth + 1)
                if found:
                    return found
        return []

    return walk(data)


async def _dismiss_cookies(page) -> None:
    try:
        btn = page.locator("button").filter(
            has_text=re.compile(r"accept|agree|ok|got it|allow", re.I)
        ).first
        await btn.click(timeout=3000)
        await asyncio.sleep(0.4)
    except Exception:
        pass


async def _dom_fallback(page) -> list[ListingStub]:
    """Minimal DOM fallback: practice links on the listing page."""
    stubs: list[ListingStub] = []
    seen: set[str] = set()
    links = page.locator('a[href*="/uk/practice/"]')
    n = await links.count()
    for i in range(min(n, 200)):
        try:
            href = await links.nth(i).get_attribute("href")
            text = (await links.nth(i).inner_text(timeout=500)).strip()
        except Exception:
            continue
        if not href:
            continue
        if not href.startswith("http"):
            href = f"https://www.doctify.com{href}"
        href = href.split("#")[0].rstrip("/")
        if href in seen or "/practice/" not in href:
            continue
        seen.add(href)
        stubs.append(ListingStub(clinic_name=text.split("\n")[0].strip(), doctify_url=href))
    return stubs


async def _scrape_listings_for_url(
    browser,
    cfg: dict[str, Any],
    skip: set[str],
    listing_delay: float,
) -> list[ListingStub]:
    ctx = await browser.new_context(user_agent=_UA, viewport={"width": 1280, "height": 800})
    page = await ctx.new_page()
    stubs: list[ListingStub] = []
    cookies_dismissed = False
    consecutive_empty = 0
    label = cfg["url"].split("/find/")[-1].split("/")[0] if "/find/" in cfg["url"] else "listing"

    try:
        for page_num in range(1, int(cfg["pages"]) + 1):
            url = build_page_url(cfg["url"], page_num)
            captured: list[ListingStub] = []

            async def _on_resp(response, _buf=captured):
                if response.status != 200:
                    return
                if "json" not in response.headers.get("content-type", ""):
                    return
                if "/webapi/" not in response.url and "/api/" not in response.url:
                    return
                try:
                    body = await response.json()
                    results = _extract_clinics_from_json(body)
                    if results:
                        _buf.extend(results)
                except Exception:
                    pass

            page.on("response", _on_resp)
            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
            except Exception:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(3)
                except Exception as exc:
                    logger.warning("[%s p%s] nav failed: %s", label, page_num, exc)
                    page.remove_listener("response", _on_resp)
                    continue

            if not cookies_dismissed:
                await _dismiss_cookies(page)
                cookies_dismissed = True

            await asyncio.sleep(1.5)
            page.remove_listener("response", _on_resp)

            if captured:
                found = []
                seen_keys: set[str] = set()
                for c in captured:
                    key = c.doctify_url
                    if key and key not in seen_keys and key not in skip:
                        seen_keys.add(key)
                        found.append(c)
            else:
                found = [c for c in await _dom_fallback(page) if c.doctify_url not in skip]

            if not found:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    logger.info("[%s] 3 empty pages — stop at p%s", label, page_num)
                    break
            else:
                consecutive_empty = 0
                stubs.extend(found)

            await asyncio.sleep(listing_delay)

        logger.info("[%s] listing done — %s stubs", label, len(stubs))
    finally:
        await ctx.close()

    return stubs


async def discover_listings(
    url_configs: list[dict[str, Any]],
    *,
    skip_urls: set[str] | None = None,
    listing_delay: float = 2.0,
    max_total: int | None = None,
) -> list[ListingStub]:
    """Scrape Doctify find/ listing pages → unique practice stubs."""
    skip = set(skip_urls or set())
    all_stubs: list[ListingStub] = []
    seen = set(skip)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for cfg in url_configs:
            if max_total is not None and len(all_stubs) >= max_total:
                break
            batch = await _scrape_listings_for_url(browser, cfg, seen, listing_delay)
            for stub in batch:
                if stub.doctify_url and stub.doctify_url not in seen:
                    seen.add(stub.doctify_url)
                    all_stubs.append(stub)
                    if max_total is not None and len(all_stubs) >= max_total:
                        break
        await browser.close()

    return all_stubs


def discover_listings_sync(
    scope_path: Path | str | None = None,
    *,
    start_url: str = "",
    pages: int | None = None,
    listing_delay: float = 2.0,
    max_total: int | None = None,
    skip_urls: set[str] | None = None,
) -> list[ListingStub]:
    if start_url:
        configs = [{"url": start_url, "pages": pages or 1}]
    else:
        configs = load_scope_csv(scope_path or DEFAULT_SCOPE)
        if pages is not None:
            for c in configs:
                c["pages"] = pages
    return asyncio.run(
        discover_listings(
            configs,
            skip_urls=skip_urls,
            listing_delay=listing_delay,
            max_total=max_total,
        )
    )
