"""Optional CQC Public API client (stub until CQC_API_KEY is present)."""

from __future__ import annotations

import logging
from typing import Any

import requests

from gtm_pipeline import config

logger = logging.getLogger(__name__)

API_BASE = "https://api.service.cqc.org.uk/public/v1"


class CqcApiClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or config.CQC_API_KEY
        if not self.api_key:
            raise RuntimeError("CQC_API_KEY is not set")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Ocp-Apim-Subscription-Key": self.api_key,
                "Accept": "application/json",
                "User-Agent": "docmap-gtm-pipeline/0.1",
            }
        )

    def get_location(self, location_id: str) -> dict[str, Any]:
        url = f"{API_BASE}/locations/{location_id}"
        r = self.session.get(url, timeout=30)
        r.raise_for_status()
        return r.json()


def maybe_client() -> CqcApiClient | None:
    if not config.CQC_API_KEY:
        logger.info("CQC_API_KEY not set — API client disabled")
        return None
    return CqcApiClient()
