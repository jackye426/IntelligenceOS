"""One-off debug script: opens Google Maps for one clinic, takes screenshots at each step,
and dumps the inner HTML of the reviews panel so we can fix selectors."""

import asyncio
import urllib.parse
from pathlib import Path
from playwright.async_api import async_playwright

CLINIC = "The Evewell - Harley Street"
ADDRESS = "61 Harley St, London, United Kingdom, W1G 8QU"
DEBUG_DIR = Path("debug")
DEBUG_DIR.mkdir(exist_ok=True)


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=300)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})

        query = f"{CLINIC} {ADDRESS}"
        url = f"https://www.google.com/maps/search/{urllib.parse.quote(query)}"
        print(f"Navigating to: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # Screenshot 1: initial load
        await page.screenshot(path=str(DEBUG_DIR / "01_initial.png"), full_page=False)
        print(f"URL after load: {page.url}")
        print("Screenshot 01_initial.png saved")

        # Handle consent.google.com redirect
        if "consent.google.com" in page.url:
            print("On consent.google.com — probing buttons:")
            btns = await page.locator('button').all()
            for btn in btns:
                try:
                    txt = await btn.inner_text(timeout=500)
                    aria = await btn.get_attribute('aria-label')
                    print(f"  button text={txt!r} aria-label={aria!r}")
                except Exception:
                    pass
            # Try clicking accept
            for sel in ['button:has-text("Accept all")', 'button:has-text("Accept")', 'form[action*="save"] button']:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=1500):
                        await btn.click()
                        print(f"  Clicked: {sel!r}")
                        await page.wait_for_url("**/maps/**", timeout=10000)
                        print(f"  Redirected to: {page.url}")
                        await asyncio.sleep(2)
                        break
                except Exception as e:
                    print(f"  {sel!r} failed: {e}")
        else:
            # Accept consent if visible
            for sel in ['button:has-text("Accept all")', 'button:has-text("Agree")']:
                try:
                    btn = page.locator(sel)
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        await asyncio.sleep(1)
                        print(f"Clicked consent: {sel}")
                        break
                except Exception:
                    pass

        await asyncio.sleep(2)
        await page.screenshot(path=str(DEBUG_DIR / "02_after_consent.png"), full_page=False)

        # Check if we're on a search results page or directly on the clinic
        feed = page.locator('[role="feed"]')
        if await feed.is_visible(timeout=2000):
            print("Search results feed detected — clicking first result")
            links = page.locator('[role="feed"] a')
            count = await links.count()
            print(f"  Found {count} links in feed")
            if count > 0:
                href = await links.first.get_attribute("href")
                print(f"  First link href: {href}")
                await links.first.click()
                await asyncio.sleep(3)
        else:
            print("No feed — looks like we're directly on the business page")

        await page.screenshot(path=str(DEBUG_DIR / "03_business_page.png"), full_page=False)
        print(f"Page title: {await page.title()}")
        print(f"Page URL: {page.url}")

        # Probe for Reviews tab
        print("\n-- Probing for Reviews tab --")
        for sel in [
            'button[aria-label*="Reviews" i]',
            '[role="tab"]:has-text("Reviews")',
            'button:has-text("Reviews")',
        ]:
            els = page.locator(sel)
            n = await els.count()
            print(f"  {sel!r}: {n} matches")
            if n > 0:
                lbl = await els.first.get_attribute("aria-label")
                txt = await els.first.inner_text()
                print(f"    aria-label={lbl!r}  text={txt!r}")

        # Try clicking Reviews tab
        try:
            rev_tab = page.locator('button[aria-label*="Reviews" i]').first
            await rev_tab.click(timeout=8000)
            print("Clicked Reviews tab")
        except Exception as e:
            print(f"Could not click Reviews tab: {e}")

        await asyncio.sleep(2)
        await page.screenshot(path=str(DEBUG_DIR / "04_reviews_tab.png"), full_page=False)

        # Probe for sort button
        print("\n-- Probing for sort button --")
        sort_sels = [
            'button[aria-label*="Sort reviews" i]',
            'button[jsaction*="pane.review.sort" i]',
            'button[jsaction*="review.sort"]',
            'button[aria-label*="Sort" i]',
        ]
        for sel in sort_sels:
            n = await page.locator(sel).count()
            print(f"  {sel!r}: {n} matches")
            if n > 0:
                lbl = await page.locator(sel).first.get_attribute("aria-label")
                txt = await page.locator(sel).first.inner_text()
                jsa = await page.locator(sel).first.get_attribute("jsaction")
                print(f"    aria-label={lbl!r}  text={txt!r}  jsaction={jsa!r}")

        # Probe for review items
        print("\n-- Probing for review item selectors --")
        review_sels = [
            '[data-review-id]',
            '.jftiEf',
            '.wiI7pd',
            '[class*="review"]',
            'div[jsaction*="review"]',
        ]
        for sel in review_sels:
            n = await page.locator(sel).count()
            print(f"  {sel!r}: {n} matches")

        # Test sort button and menu
        print("\n-- Testing sort button --")
        try:
            sort_btn = page.locator('button[aria-label="Sort reviews"]').first
            await sort_btn.click(timeout=5000)
            await asyncio.sleep(1)
            await page.screenshot(path=str(DEBUG_DIR / "05_sort_menu.png"), full_page=False)
            print("Sort menu opened")
            menu_items = page.locator('[role="menuitem"], [role="option"]')
            n = await menu_items.count()
            print(f"  menuitem/option: {n} items")
            # Probe more broadly
            for probe_sel in [
                '[role="menuitem"]', '[role="option"]', '[role="listitem"]',
                '[role="radio"]', 'li', '.fxNQSd', '.hH0dDd', 'div[jsaction*="sort"]',
                'div:has-text("Lowest rating")', 'span:has-text("Lowest rating")',
            ]:
                pn = await page.locator(probe_sel).count()
                if pn > 0:
                    try:
                        ptxt = await page.locator(probe_sel).first.inner_text(timeout=300)
                        print(f"  {probe_sel!r}: {pn} | first text={ptxt[:40]!r}")
                    except Exception:
                        print(f"  {probe_sel!r}: {pn}")
            # Click "Lowest rating" via has-text
            await page.locator('div:has-text("Lowest rating"):last-child, li:has-text("Lowest rating")').last.click(timeout=3000)
            await asyncio.sleep(2)
            print("Clicked Lowest rating")
            await page.screenshot(path=str(DEBUG_DIR / "06_sorted_reviews.png"), full_page=False)
            # Check what we get now
            els = page.locator('[data-review-id]')
            print(f"  {await els.count()} review elements after sorting")
            # Check first review rating
            if await els.count() > 0:
                star = await els.first.locator('span[aria-label*="star"]').first.get_attribute('aria-label', timeout=2000)
                print(f"  First review rating: {star!r}")
        except Exception as e:
            print(f"Sort test failed: {e}")

        # Probe star rating selectors inside first few review elements
        print("\n-- Probing rating selectors inside [data-review-id] elements --")
        review_els = page.locator('[data-review-id]')
        for i in range(min(3, await review_els.count())):
            el = review_els.nth(i)
            print(f"\n  Review #{i+1}:")
            for sel in [
                '[role="img"]',
                'span[aria-label*="star" i]',
                'span[aria-label*="out of" i]',
                'span[aria-label*="Rated" i]',
                'span[aria-label*="star"]',
                '.kvMYJc',
                '.lTi8oc',
            ]:
                inner = el.locator(sel)
                n = await inner.count()
                if n > 0:
                    lbl = await inner.first.get_attribute('aria-label')
                    cls = await inner.first.get_attribute('class')
                    print(f"    {sel!r}: {n} | aria-label={lbl!r} class={cls!r}")
            # Review text selector
            for sel in ['.wiI7pd', '.rsqaWe', 'span[jscontroller]']:
                inner = el.locator(sel)
                if await inner.count() > 0:
                    try:
                        txt = await inner.first.inner_text(timeout=1000)
                        print(f"    text via {sel!r}: {txt[:80]!r}")
                    except Exception:
                        pass

        await asyncio.sleep(2)
        await browser.close()
        print(f"\nDone. Screenshots in: {DEBUG_DIR.resolve()}")


asyncio.run(run())
