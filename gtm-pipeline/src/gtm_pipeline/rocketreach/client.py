"""RocketReach person lookup client.

Uses GET https://api.rocketreach.co/api/v2/person/lookup when ROCKETREACH_API_KEY
is set. Polls /person/checkStatus when lookup returns progress/searching/waiting.
Modes: search (default), noop/off (no network).
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

import requests

from gtm_pipeline import config

logger = logging.getLogger(__name__)

LOOKUP_URL = "https://api.rocketreach.co/api/v2/person/lookup"
CHECK_STATUS_URL = "https://api.rocketreach.co/api/v2/person/checkStatus"

_INCOMPLETE = {"progress", "searching", "waiting", "not queued", "queued"}


def rocketreach_mode() -> str:
    return (os.getenv("GTM_ROCKETREACH_MODE") or "search").strip().lower()


def rocketreach_configured() -> bool:
    return bool(config.ROCKETREACH_API_KEY)


def _clean_person_name(name: str) -> str:
    """Strip common clinical titles for better RR name match."""
    s = (name or "").strip()
    s = re.sub(
        r"^(dr\.?|miss|mrs\.?|ms\.?|mr\.?|prof\.?|professor)\s+",
        "",
        s,
        flags=re.I,
    )
    return re.sub(r"\s+", " ", s).strip()


def _pick_best_email(emails: list[dict[str, Any]]) -> tuple[str | None, float]:
    """Return (email, confidence). Prefer professional + valid SMTP + high grade."""
    if not emails:
        return None, 0.0
    scored: list[tuple[float, str]] = []
    for e in emails:
        addr = (e.get("email") or "").strip()
        if not addr:
            continue
        grade = (e.get("grade") or "").upper()
        etype = (e.get("type") or "").lower()
        valid = str(e.get("valid") or e.get("smtp_valid") or "").lower()
        if valid in {"invalid", "false"}:
            continue  # skip known-invalid
        score = 0.45
        if etype == "professional":
            score += 0.3
        elif etype == "personal":
            score += 0.05
        if grade in {"A", "A+"}:
            score += 0.2
        elif grade == "B":
            score += 0.1
        elif grade in {"C", "D"}:
            score += 0.0
        elif grade == "F":
            score -= 0.2
        if valid in {"true", "valid"}:
            score += 0.15
        scored.append((min(0.99, max(0.1, score)), addr))
    if not scored:
        # fallback: take highest-grade even if smtp invalid marked
        for e in emails:
            addr = (e.get("email") or "").strip()
            if addr:
                return addr, 0.4
        return None, 0.0
    scored.sort(reverse=True)
    return scored[0][1], scored[0][0]


def _request_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: int = 45,
) -> tuple[int, dict[str, Any] | list[Any] | None]:
    headers = {"Api-Key": config.ROCKETREACH_API_KEY}
    r = requests.get(url, headers=headers, params=params or {}, timeout=timeout)
    if r.status_code == 429:
        retry = int(r.headers.get("Retry-After", "5"))
        time.sleep(min(60, max(1, retry)))
        r = requests.get(url, headers=headers, params=params or {}, timeout=timeout)
    if r.status_code == 404:
        return 404, None
    r.raise_for_status()
    if not r.content:
        return r.status_code, {}
    return r.status_code, r.json()


def _poll_until_complete(
    profile_id: int | str,
    *,
    max_wait_s: float = 45.0,
    interval_s: float = 2.5,
) -> dict[str, Any]:
    """Poll checkStatus (no credits) until complete/failed or timeout."""
    deadline = time.time() + max_wait_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        try:
            # API accepts ids as repeated query param
            code, data = _request_json(
                CHECK_STATUS_URL,
                params={"ids": str(profile_id)},
            )
        except Exception as exc:
            logger.warning("rocketreach checkStatus failed id=%s: %s", profile_id, exc)
            break
        if code == 404 or data is None:
            break
        # Response may be a list of profiles or a single object / dict wrapper
        if isinstance(data, list):
            row = next((x for x in data if str(x.get("id")) == str(profile_id)), data[0] if data else {})
        elif isinstance(data, dict):
            if "id" in data:
                row = data
            else:
                # sometimes { "people": [...] }
                people = data.get("people") or data.get("profiles") or []
                row = people[0] if people else data
        else:
            row = {}
        last = row if isinstance(row, dict) else {}
        st = (last.get("status") or "").lower()
        if st in {"complete", "failed"} or (last.get("emails") and st not in _INCOMPLETE):
            return last
        time.sleep(interval_s)
    return last


def _normalize_result(data: dict[str, Any]) -> dict[str, Any]:
    emails = list(data.get("emails") or [])
    best, conf = _pick_best_email(emails)
    li = (data.get("linkedin_url") or "").strip()
    rr_status = (data.get("status") or "").lower()

    if rr_status == "failed":
        return {
            "status": "failed",
            "email": best or "",
            "emails": emails,
            "confidence": conf,
            "linkedin_url": li,
            "rocketreach_id": data.get("id"),
            "raw": data,
        }

    pro_valid = [
        e
        for e in emails
        if (e.get("email") or "").strip()
        and (e.get("type") or "").lower() == "professional"
        and str(e.get("smtp_valid") or e.get("valid") or "").lower()
        in {"valid", "true", ""}
    ]
    if len(pro_valid) >= 3 and conf < config.MATCH_AUTO_ACCEPT:
        return {
            "status": "ambiguous",
            "email": best or "",
            "emails": emails,
            "confidence": conf,
            "linkedin_url": li,
            "rocketreach_id": data.get("id"),
            "raw": data,
        }

    if not best and not li:
        return {
            "status": "none",
            "email": "",
            "emails": emails,
            "confidence": 0.0,
            "linkedin_url": "",
            "rocketreach_id": data.get("id"),
            "raw": data,
        }

    if best and conf >= config.MATCH_AUTO_ACCEPT:
        status = "found"
    elif best and conf >= config.MATCH_REVIEW_THRESHOLD:
        status = "ambiguous"
    elif best:
        status = "ambiguous"
    elif li:
        # LinkedIn found but no usable email yet
        status = "found"
        conf = max(conf, 0.55)
    else:
        status = "none"

    return {
        "status": status,
        "email": best or "",
        "emails": emails,
        "confidence": conf,
        "linkedin_url": li,
        "rocketreach_id": data.get("id"),
        "raw": data,
    }


def lookup_person(
    name: str,
    *,
    current_employer: str = "",
    linkedin_url: str = "",
    poll: bool = True,
    max_wait_s: float = 45.0,
) -> dict[str, Any]:
    """Lookup a person; returns status + emails + optional linkedin."""
    mode = rocketreach_mode()
    if mode in {"noop", "off", "skip"}:
        return {
            "status": "skipped",
            "email": "",
            "emails": [],
            "confidence": 0.0,
            "linkedin_url": "",
            "rocketreach_id": None,
            "raw": {},
        }

    if not rocketreach_configured():
        return {
            "status": "skipped",
            "email": "",
            "emails": [],
            "confidence": 0.0,
            "linkedin_url": "",
            "rocketreach_id": None,
            "raw": {},
            "error": "ROCKETREACH_API_KEY not set",
        }

    params: dict[str, str] = {}
    if (linkedin_url or "").strip():
        params["linkedin_url"] = linkedin_url.strip()
    else:
        cleaned = _clean_person_name(name)
        params["name"] = cleaned or (name or "").strip()
        if current_employer:
            params["current_employer"] = current_employer.strip()

    if not params.get("name") and not params.get("linkedin_url"):
        return {
            "status": "failed",
            "email": "",
            "emails": [],
            "confidence": 0.0,
            "error": "missing name",
            "raw": {},
        }

    try:
        code, data = _request_json(LOOKUP_URL, params=params)
        if code == 404 or data is None:
            return {
                "status": "none",
                "email": "",
                "emails": [],
                "confidence": 0.0,
                "linkedin_url": "",
                "rocketreach_id": None,
                "raw": {},
            }
        if not isinstance(data, dict):
            return {
                "status": "failed",
                "email": "",
                "emails": [],
                "confidence": 0.0,
                "error": "unexpected_response",
                "raw": {"data": data},
            }
    except Exception as exc:
        logger.warning("rocketreach lookup failed for %s: %s", name, exc)
        return {
            "status": "failed",
            "email": "",
            "emails": [],
            "confidence": 0.0,
            "error": str(exc),
            "raw": {},
        }

    st = (data.get("status") or "").lower()
    pid = data.get("id")
    if poll and pid and st in _INCOMPLETE:
        logger.info("rocketreach polling id=%s status=%s", pid, st)
        polled = _poll_until_complete(pid, max_wait_s=max_wait_s)
        if polled:
            data = polled

    return _normalize_result(data)
