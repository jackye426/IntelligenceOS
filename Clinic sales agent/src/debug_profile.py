"""Check what contact info is available on Doctify clinic profiles."""
import asyncio
import re
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

TEST_PROFILES = [
    'https://www.doctify.com/uk/practice/london-gynaecology-harley-street',
    'https://www.doctify.com/uk/practice/london-medical',
    'https://www.doctify.com/uk/practice/womens-health-centre',
]

EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
PHONE_RE = re.compile(r'(\+44|0)[0-9 \-\(\)]{9,15}')


async def check_profile(page, url):
    print(f"\n{'='*60}")
    print(f"Profile: {url}")
    try:
        await page.goto(url, wait_until='networkidle', timeout=20000)
    except Exception:
        await page.goto(url, wait_until='domcontentloaded', timeout=20000)
        await asyncio.sleep(2)

    html = await page.content()
    soup = BeautifulSoup(html, 'lxml')
    text = soup.get_text(separator=' ')

    # Emails in page text
    emails = list(set(EMAIL_RE.findall(text)))
    emails = [e for e in emails if 'doctify' not in e and 'sentry' not in e and '.png' not in e]
    print(f"Emails found: {emails}")

    # Phone numbers
    phones = list(set(PHONE_RE.findall(text)))
    print(f"Phones found: {phones[:5]}")

    # mailto: links
    mailtos = [a['href'] for a in soup.find_all('a', href=re.compile(r'^mailto:'))]
    print(f"mailto links: {mailtos}")

    # Look for a contact section
    for el in soup.find_all(['p', 'span', 'div', 'a']):
        t = el.get_text(strip=True)
        if EMAIL_RE.search(t) and 'doctify' not in t:
            print(f"Contact element ({el.name}): {t[:100]!r}")

    # Check __NEXT_DATA__ for phone/email fields
    script = soup.find('script', id='__NEXT_DATA__')
    if script and script.string:
        import json
        try:
            raw = script.string
            for field in ['"email"', '"phone"', '"telephone"', '"contactEmail"', '"enquiryEmail"']:
                idx = raw.find(field)
                if idx != -1:
                    snippet = raw[idx:idx+150]
                    m = re.search(r':\s*"([^"]{3,})"', snippet)
                    if m:
                        print(f"  __NEXT_DATA__ {field}: {m.group(1)!r}")
        except Exception:
            pass


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
        )
        page = await ctx.new_page()
        for url in TEST_PROFILES:
            await check_profile(page, url)
        await browser.close()

asyncio.run(main())
