"""
Debug: inspect specialists and keywords_search fields in __NEXT_DATA__.
"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

URL = "https://www.doctify.com/uk/find/urology/harley-street/practices#distance=5"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
            viewport={'width': 1280, 'height': 800},
        )
        page = await ctx.new_page()
        try:
            await page.goto(URL, wait_until='networkidle', timeout=30000)
        except Exception:
            pass
        await asyncio.sleep(2)
        html = await page.content()
        await browser.close()

    soup = BeautifulSoup(html, 'lxml')
    script = soup.find('script', id='__NEXT_DATA__')
    if not script:
        print("No __NEXT_DATA__")
        return

    data = json.loads(script.string)
    practices = data.get('props', {}).get('pageProps', {}).get('practices', [])
    print(f"Practices count: {len(practices)}")

    for i, p in enumerate(practices[:3]):
        print(f"\n=== Clinic {i+1}: {p.get('name', {}).get('en', '?')} ===")
        print(f"  specialists: {repr(p.get('specialists'))}")
        print(f"  keywords type: {type(p.get('keywords')).__name__}, value: {repr(p.get('keywords'))[:200]}")
        print(f"  keywords_search type: {type(p.get('keywords_search')).__name__}")
        ks = p.get('keywords_search')
        if isinstance(ks, list):
            print(f"  keywords_search len={len(ks)}, first 3:")
            for kw in ks[:3]:
                print(f"    {repr(kw)[:120]}")
        elif isinstance(ks, dict):
            print(f"  keywords_search keys: {list(ks.keys())[:10]}")
        else:
            print(f"  keywords_search: {repr(ks)[:200]}")

asyncio.run(main())
