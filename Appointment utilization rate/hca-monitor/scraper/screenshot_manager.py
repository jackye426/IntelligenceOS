import logging
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Page

from config.settings import settings

logger = logging.getLogger(__name__)


async def save_screenshot(page: Page, label: str) -> str | None:
    """Save a screenshot and return the file path. Never raises — failures are logged only."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
    filename = f"{ts}_{safe_label}.png"
    path = Path(settings.screenshot_dir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(path), full_page=True, timeout=10000)
        logger.debug("Screenshot saved: %s", path)
        return str(path)
    except Exception as e:
        logger.debug("Screenshot failed (%s): %s", label, e)
        return None
