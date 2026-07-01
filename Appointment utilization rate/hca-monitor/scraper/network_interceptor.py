"""
Attach Playwright request/response listeners to capture API calls made during
the booking flow. Saves all JSON responses for later inspection.

Usage:
    interceptor = NetworkInterceptor()
    interceptor.attach(page)
    # ... drive the booking flow ...
    endpoints = interceptor.get_candidate_endpoints()
    slot_response = interceptor.get_slot_api_response()
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

from playwright.async_api import Page, Request, Response

logger = logging.getLogger(__name__)

# Keywords that suggest an endpoint carries availability/slot data
_SLOT_KEYWORDS = [
    "availab", "slot", "appointment", "calendar", "schedule",
    "booking", "timeslot", "session", "capacity",
]


@dataclass
class CandidateEndpoint:
    url: str
    method: str
    query_params: dict
    request_body: str | None
    response_status: int
    response_json: dict | list | None
    timing_ms: float
    requires_session: bool = False  # True if non-public auth headers present
    slot_ids_in_response: list = field(default_factory=list)
    looks_like_slots: bool = False


class NetworkInterceptor:
    def __init__(self) -> None:
        self._candidates: list[CandidateEndpoint] = []
        self._request_times: dict[str, float] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach(self, page: Page) -> None:
        """Register listeners. Must be called before navigation."""
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        logger.debug("NetworkInterceptor attached to page")

    def _on_request(self, request: Request) -> None:
        import time
        if self._is_json_candidate(request):
            self._request_times[request.url] = time.monotonic()

    def _on_response(self, response: Response) -> None:
        asyncio.ensure_future(self._handle_response(response))

    async def _handle_response(self, response: Response) -> None:
        import time
        url = response.url
        method = response.request.method

        if not self._is_json_url(url):
            return

        # Measure timing
        start = self._request_times.pop(url, None)
        timing_ms = (time.monotonic() - start) * 1000 if start else 0.0

        # Parse query string
        parsed = urlparse(url)
        query_params = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}

        # Read request body
        try:
            body_bytes = response.request.post_data_buffer
            request_body = body_bytes.decode("utf-8", errors="replace") if body_bytes else None
        except Exception:
            request_body = None

        # Read response JSON — try harder for HCA API endpoints
        response_json = None
        try:
            content_type = response.headers.get("content-type", "")
            if "json" in content_type or "hcahealthcare.co.uk/api/" in url.lower():
                response_json = await response.json(content_type=None)
        except Exception as e:
            logger.debug("Could not parse JSON from %s: %s", url, e)

        # Check for non-public auth signals
        req_headers = response.request.headers
        requires_session = any(
            h in req_headers for h in ["authorization", "x-auth-token", "x-api-key", "cookie"]
            if req_headers.get(h, "").startswith("Bearer ") or "session" in req_headers.get(h, "").lower()
        )

        # Extract slot IDs if present
        slot_ids = _extract_slot_ids(response_json)
        looks_like_slots = _assess_slot_likelihood(url, response_json)

        endpoint = CandidateEndpoint(
            url=url,
            method=method,
            query_params=query_params,
            request_body=request_body,
            response_status=response.status,
            response_json=response_json,
            timing_ms=timing_ms,
            requires_session=requires_session,
            slot_ids_in_response=slot_ids,
            looks_like_slots=looks_like_slots,
        )
        self._candidates.append(endpoint)

        if looks_like_slots:
            logger.info("Slot-like API response detected: %s (status=%d)", url, response.status)

    @staticmethod
    def _is_json_url(url: str) -> bool:
        skip_exts = (".png", ".jpg", ".gif", ".svg", ".woff", ".woff2", ".ttf", ".css", ".ico")
        return not any(url.lower().split("?")[0].endswith(ext) for ext in skip_exts)

    @staticmethod
    def _is_json_candidate(request: Request) -> bool:
        return NetworkInterceptor._is_json_url(request.url)

    def get_candidate_endpoints(self) -> list[CandidateEndpoint]:
        return list(self._candidates)

    def get_slot_api_response(self) -> CandidateEndpoint | None:
        """Return the most slot-like endpoint captured, or None."""
        slot_endpoints = [e for e in self._candidates if e.looks_like_slots and e.response_json]
        if not slot_endpoints:
            return None
        # Prefer the one with the most slot IDs
        return max(slot_endpoints, key=lambda e: len(e.slot_ids_in_response), default=None)

    def dump_log(self, path: str) -> None:
        """Write all captured endpoints to a JSON file for manual inspection."""
        import json as _json
        from pathlib import Path
        records = []
        for ep in self._candidates:
            records.append({
                "url": ep.url,
                "method": ep.method,
                "query_params": ep.query_params,
                "request_body": ep.request_body,
                "response_status": ep.response_status,
                "timing_ms": round(ep.timing_ms, 1),
                "requires_session": ep.requires_session,
                "looks_like_slots": ep.looks_like_slots,
                "slot_ids_count": len(ep.slot_ids_in_response),
                "response_json_preview": _truncate_json(ep.response_json, max_chars=500),
            })
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(records, f, indent=2, default=str)
        logger.info("Network log written to %s (%d endpoints)", path, len(records))


def _extract_slot_ids(data: dict | list | None) -> list:
    if not data:
        return []
    ids = []
    _walk_for_ids(data, ids)
    return ids[:50]  # cap to avoid huge lists


def _walk_for_ids(obj, ids: list, depth: int = 0) -> None:
    if depth > 5:
        return
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key.lower() in ("id", "slotid", "slot_id", "appointmentid", "appointment_id"):
                if isinstance(val, (str, int)):
                    ids.append(val)
            _walk_for_ids(val, ids, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _walk_for_ids(item, ids, depth + 1)


def _assess_slot_likelihood(url: str, data: dict | list | None) -> bool:
    url_lower = url.lower()
    if any(kw in url_lower for kw in _SLOT_KEYWORDS):
        return True
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        keys = set(data[0].keys())
        slot_keys = {"startTime", "endTime", "start", "end", "time", "date", "available",
                     "slotTime", "slot_time", "appointmentTime"}
        if keys & slot_keys:
            return True
    if isinstance(data, dict):
        for kw in _SLOT_KEYWORDS:
            if any(kw in k.lower() for k in data.keys()):
                return True
    return False


def _truncate_json(obj, max_chars: int = 500) -> str:
    if obj is None:
        return "null"
    try:
        s = json.dumps(obj, default=str)
        return s[:max_chars] + ("..." if len(s) > max_chars else "")
    except Exception:
        return str(obj)[:max_chars]
