import asyncio
import json
import random
import urllib.parse
from pathlib import Path
from slugify import slugify
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)


async def _sleep(low=1.0, high=2.5):
    await asyncio.sleep(random.uniform(low, high))


async def _handle_consent(page):
    """Handle Google's GDPR consent page (consent.google.com) if we land on it."""
    if "consent.google.com" not in page.url:
        return
    try:
        await page.click('button:has-text("Accept all")', timeout=5000)
        await page.wait_for_url("**/maps/**", timeout=15000)
        await _sleep(1.5, 2.5)
    except Exception:
        pass


async def _scroll_reviews_panel(page):
    """Scroll the reviews panel to trigger lazy-loading of more reviews."""
    await page.evaluate("""
        () => {
            const el = document.querySelector('[data-review-id]');
            if (!el) return;
            let p = el.parentElement;
            while (p && p !== document.body) {
                if (p.scrollHeight > p.clientHeight + 50) {
                    p.scrollBy(0, 1500);
                    return;
                }
                p = p.parentElement;
            }
            window.scrollBy(0, 1500);
        }
    """)


async def _expand_truncated_reviews(page):
    """Click all 'More' buttons to expand truncated review text."""
    try:
        btns = page.locator('button.w8nwRe, button[aria-label="See more"]')
        count = await btns.count()
        for i in range(count):
            try:
                await btns.nth(i).click(timeout=600)
                await asyncio.sleep(0.1)
            except Exception:
                pass
    except Exception:
        pass


async def _extract_visible_reviews(page, seen_ids):
    """Extract any new negative reviews (<=3 stars) currently rendered."""
    new_reviews = []
    try:
        els = page.locator('[data-review-id]')
        count = await els.count()
    except Exception:
        return new_reviews

    for i in range(count):
        el = els.nth(i)
        try:
            rid = await el.get_attribute('data-review-id') or f"idx_{i}"
            if rid in seen_ids:
                continue

            # Rating — aria-label format: "3 stars"
            star_el = el.locator('span[aria-label*="star"], .kvMYJc').first
            aria = await star_el.get_attribute('aria-label', timeout=1500) or ""
            # Extract first numeric token from aria-label
            digits = [int(tok) for tok in aria.split() if tok.isdigit()]
            rating = digits[0] if digits else None
            if not rating or rating > 3:
                seen_ids.add(rid)
                continue

            # Review text
            text_el = el.locator('.wiI7pd').first
            text = ""
            if await text_el.count() > 0:
                text = (await text_el.inner_text(timeout=2000)).strip()
            if not text:
                seen_ids.add(rid)
                continue

            # Date (relative e.g. "3 months ago")
            date_el = el.locator('.rsqaWe').first
            date = ""
            if await date_el.count() > 0:
                date = (await date_el.inner_text(timeout=1500)).strip()

            seen_ids.add(rid)
            new_reviews.append({"rating": rating, "date": date, "text": text})
        except Exception:
            continue

    return new_reviews


async def scrape_clinic(page, clinic_name, address="", max_reviews=100, refresh=False):
    """Scrape negative reviews (<=3 stars) for one clinic from Google Maps."""
    slug = slugify(clinic_name)
    cache_file = DATA_DIR / f"{slug}.json"

    if cache_file.exists() and not refresh:
        print(f"  [cache] {clinic_name}")
        return json.loads(cache_file.read_text(encoding="utf-8"))

    print(f"  [scrape] {clinic_name}")

    query = f"{clinic_name} {address}".strip()
    try:
        await page.goto(
            f"https://www.google.com/maps/search/{urllib.parse.quote(query)}",
            wait_until="domcontentloaded",
            timeout=30000,
        )
    except PlaywrightTimeout:
        print(f"  [timeout] Navigation timed out for {clinic_name}")
        return _empty_result(clinic_name)

    await _handle_consent(page)
    await _sleep(1.5, 2.5)

    # If we landed on a search-results list, click the first business entry
    try:
        first_link = page.locator('[role="feed"] a[href*="/maps/place/"]').first
        if await first_link.is_visible(timeout=2000):
            await first_link.click()
            await _sleep(1.5, 2.5)
    except Exception:
        pass

    # Click the Reviews tab — use the exact role="tab" selector confirmed via debugging
    try:
        reviews_tab = page.locator('[role="tab"]:has-text("Reviews")').first
        await reviews_tab.click(timeout=10000)
        await _sleep(1.0, 2.0)
    except Exception:
        print(f"  [warn] No Reviews tab found for {clinic_name}")
        return _empty_result(clinic_name)

    # Sort by lowest rating using .fxNQSd (Google Maps sort menu item class)
    try:
        await page.locator('button[aria-label="Sort reviews"]').first.click(timeout=5000)
        await _sleep(0.6, 1.0)
        await page.locator('.fxNQSd:has-text("Lowest rating")').first.click(timeout=5000)
        await _sleep(1.5, 2.5)
    except Exception:
        print(f"  [warn] Could not sort by lowest rating for {clinic_name}")

    # Scroll and collect reviews
    reviews = []
    seen_ids: set[str] = set()
    no_new_streak = 0

    while len(reviews) < max_reviews and no_new_streak < 4:
        await _expand_truncated_reviews(page)
        new = await _extract_visible_reviews(page, seen_ids)
        reviews.extend(new)
        no_new_streak = 0 if new else no_new_streak + 1
        await _scroll_reviews_panel(page)
        await _sleep(0.8, 1.5)

    reviews = reviews[:max_reviews]
    result = {
        "clinic": clinic_name,
        "reviews": reviews,
        "total_negative": len(reviews),
    }
    cache_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [done] {clinic_name}: {len(reviews)} negative reviews collected")
    return result


def _empty_result(clinic_name):
    return {"clinic": clinic_name, "reviews": [], "total_negative": 0}


async def scrape_all(clinics, max_reviews=100, headless=False, refresh=False):
    """Scrape all clinics sequentially, sharing one browser instance."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        results = []
        for i, clinic in enumerate(clinics):
            print(f"\n[{i+1}/{len(clinics)}] {clinic['name']}")
            try:
                result = await scrape_clinic(
                    page,
                    clinic["name"],
                    clinic.get("address", ""),
                    max_reviews=max_reviews,
                    refresh=refresh,
                )
                results.append(result)
            except Exception as e:
                print(f"  [error] {clinic['name']}: {e}")
                results.append({**_empty_result(clinic["name"]), "error": str(e)})

            await _sleep(2.0, 4.0)

        await browser.close()

    return results
