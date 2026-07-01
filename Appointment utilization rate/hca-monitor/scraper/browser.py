import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from playwright.async_api import Browser, BrowserContext, async_playwright

from config.settings import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def create_browser_context() -> AsyncGenerator[tuple[Browser, BrowserContext], None]:
    """Yield (browser, context) sharing session state across all pages in one scrape run."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=settings.headless,
            slow_mo=settings.slow_mo_ms,
        )
        context = await browser.new_context(
            timezone_id="Europe/London",
            locale="en-GB",
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            extra_http_headers={"Accept-Language": "en-GB,en;q=0.9"},
        )
        logger.info("Browser context created (headless=%s)", settings.headless)
        try:
            yield browser, context
        finally:
            await context.close()
            await browser.close()
            logger.info("Browser context closed")
