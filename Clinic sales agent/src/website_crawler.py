"""
Crawls a clinic website using plain HTTP requests (fast, no JS overhead).
Prioritises pages relevant to women's health / endometriosis sales context.
Caps at MAX_PAGES_PER_CLINIC pages per run.
"""

import time
from typing import Optional
from urllib.parse import urlparse, urljoin
from collections import deque

import requests
from bs4 import BeautifulSoup
import trafilatura

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from config import MAX_PAGES_PER_CLINIC, REQUEST_TIMEOUT
from utils import log

PRIORITY_KEYWORDS = [
    'about', 'team', 'staff', 'services', 'gynaecol', 'womens', "women's",
    'endometriosis', 'pelvic', 'fertil', 'fee', 'price', 'cost',
    'insurance', 'contact', 'book', 'appointment',
]

SKIP_KEYWORDS = [
    'blog', 'news', 'privacy', 'cookie', 'terms', 'careers', 'jobs',
    'press', 'sitemap', 'login', 'register', 'admin', 'wp-admin',
    '/tag/', '/category/', '/author/', '/archive/', 'feed', '.rss',
    'javascript:', 'mailto:', 'tel:', 'whatsapp',
]

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-GB,en;q=0.9',
}


def crawl_website(url: str) -> dict:
    result = {'website_url': url, 'pages': []}

    if not url or not url.startswith('http'):
        return result

    base_domain = urlparse(url).netloc
    visited = set()

    homepage = _fetch(url)
    if not homepage:
        return result

    result['pages'].append({'url': url, 'title': homepage['title'], 'text': homepage['text']})
    visited.add(_norm(url))

    links = _internal_links(homepage['html'], url, base_domain)
    queue = deque(_prioritise(links))

    while queue and len(result['pages']) < MAX_PAGES_PER_CLINIC:
        next_url = queue.popleft()
        norm = _norm(next_url)
        if norm in visited:
            continue
        visited.add(norm)

        data = _fetch(next_url)
        if data and data['text']:
            result['pages'].append({
                'url': next_url,
                'title': data['title'],
                'text': data['text'],
            })
            # Surface priority links from this page too, but keep queue tight
            more = _internal_links(data['html'], next_url, base_domain)
            new = _prioritise([l for l in more if _norm(l) not in visited])
            queue.extend(new[:3])

        time.sleep(0.4)

    return result


def _fetch(url: str) -> Optional[dict]:
    try:
        resp = requests.get(
            url, headers=HEADERS, timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )
        if resp.status_code != 200:
            return None
        html = resp.text
        return {
            'html': html,
            'title': _title(html),
            'text': _extract_text(html),
        }
    except Exception:
        return None


def _title(html: str) -> str:
    soup = BeautifulSoup(html, 'lxml')
    tag = soup.find('title')
    return tag.get_text(strip=True) if tag else ''


def _extract_text(html: str) -> str:
    text = trafilatura.extract(
        html, include_comments=False, include_tables=True, no_fallback=False
    )
    if text and len(text.strip()) > 100:
        return text.strip()

    soup = BeautifulSoup(html, 'lxml')
    for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'noscript']):
        tag.decompose()
    return soup.get_text(separator='\n', strip=True)


def _internal_links(html: str, base_url: str, base_domain: str) -> list:
    soup = BeautifulSoup(html, 'lxml')
    links = []
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        if not href or href.startswith('#'):
            continue
        full = urljoin(base_url, href).split('#')[0]
        parsed = urlparse(full)
        if parsed.netloc == base_domain and full not in links:
            links.append(full)
    return links


def _prioritise(links: list) -> list:
    priority, normal = [], []
    for url in links:
        lower = url.lower()
        if any(k in lower for k in SKIP_KEYWORDS):
            continue
        if any(k in lower for k in PRIORITY_KEYWORDS):
            priority.append(url)
        else:
            normal.append(url)
    return priority + normal


def _norm(url: str) -> str:
    return url.rstrip('/').lower().split('?')[0]
