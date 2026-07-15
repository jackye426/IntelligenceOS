"""LinkedIn profile find for outreach contacts (and people mirror).

Does not overwrite clinic specialties/services. Runs for every PIC contact
missing a LinkedIn URL — including those who already have email.
Set GTM_LINKEDIN_FIND_MODE=noop to skip network.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any
from urllib.parse import quote_plus

import requests

from gtm_pipeline.shared.provenance import evidence_item, make_provenance, utc_now_iso
from gtm_pipeline.shared.supabase_client import get_client, supabase_configured
from gtm_pipeline.sync.match_reviews import maybe_queue_match_review

logger = logging.getLogger(__name__)

_LI_URL_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/in/[a-zA-Z0-9\-_%]+/?",
    re.I,
)


def find_mode() -> str:
    return (os.getenv("GTM_LINKEDIN_FIND_MODE") or "search").strip().lower()


def search_linkedin_profile_url(
    person_name: str,
    *,
    clinic_name: str = "",
) -> dict[str, Any]:
    """Best-effort public search for a LinkedIn /in/ URL.

    Prefer Playwright Bing (bot-resistant). Fall back to HTML DDG/Bing requests.
    """
    mode = find_mode()
    if mode in {"noop", "off", "skip"}:
        return {"status": "skipped", "linkedin_url": "", "candidates": []}

    query = f'site:linkedin.com/in "{person_name}"'
    if clinic_name:
        query += f' "{clinic_name}"'

    cleaned = _search_linkedin_playwright(query)
    if not cleaned:
        cleaned = _search_linkedin_http(query)

    if not cleaned:
        return {"status": "none", "linkedin_url": "", "candidates": []}
    if len(cleaned) == 1:
        return {"status": "found", "linkedin_url": cleaned[0], "candidates": cleaned}
    return {
        "status": "ambiguous",
        "linkedin_url": "",
        "candidates": cleaned[:5],
    }


def _extract_li_urls(html: str) -> list[str]:
    from urllib.parse import unquote

    found = list(dict.fromkeys(_LI_URL_RE.findall(html or "")))
    for m in re.findall(r"(?:uddg|u)=([^&\"']+)", html or ""):
        found.extend(_LI_URL_RE.findall(unquote(m)))
    cleaned: list[str] = []
    for u in found:
        u = u.split("?")[0].rstrip("/")
        if "linkedin.com/in/" in u.lower():
            cleaned.append(u)
    return list(dict.fromkeys(cleaned))


def _search_linkedin_http(query: str) -> list[str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-GB,en;q=0.9",
    }
    engines = [
        f"https://www.bing.com/search?q={quote_plus(query)}",
        f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
    ]
    for url in engines:
        try:
            r = requests.get(url, headers=headers, timeout=25)
            r.raise_for_status()
            cleaned = _extract_li_urls(r.text)
            if cleaned:
                return cleaned
        except Exception as exc:
            logger.warning("linkedin http search failed %s: %s", url[:48], exc)
    return []


def _search_linkedin_playwright(query: str) -> list[str]:
    """Use Chromium to render Bing results (avoids DDG bot wall)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []

    url = f"https://www.bing.com/search?q={quote_plus(query)}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(1500)
                html = page.content()
            finally:
                browser.close()
        return _extract_li_urls(html)
    except Exception as exc:
        logger.warning("linkedin playwright search failed: %s", exc)
        return []


def apply_linkedin_find_result(
    *,
    person_id: str | None,
    clinic_intelligence_id: str | None,
    clinic_account_id: str | None,
    clinic_name: str,
    person_name: str,
    result: dict[str, Any],
    dry_run: bool = False,
    contact_id: str | None = None,
) -> dict[str, Any]:
    """Persist a search result onto outreach contacts (+ optional people mirror)."""
    status = result.get("status") or "none"
    entry = {
        "person_id": person_id,
        "contact_id": contact_id,
        "name": person_name,
        "status": status,
        "linkedin_url": result.get("linkedin_url") or "",
        "candidates": result.get("candidates") or [],
    }
    if dry_run or not supabase_configured():
        return entry
    if status == "skipped":
        return entry

    client = get_client()
    li_url = (result.get("linkedin_url") or "").strip() or None

    if contact_id:
        rows = (
            client.table("gtm_outreach_contacts")
            .select("*")
            .eq("id", contact_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        contact = rows[0] if rows else None
        if contact:
            from gtm_pipeline.contacts.pic import (
                derive_contact_status,
                derive_preferred_channel,
            )

            ev = list(contact.get("evidence") or [])
            ev.append(
                evidence_item(
                    kind="linkedin_find",
                    value=result,
                    source="linkedin_find",
                    confidence=0.7 if status == "found" else 0.4,
                )
            )
            email = contact.get("email")
            url = li_url or contact.get("linkedin_url")
            preferred = derive_preferred_channel(email=email, linkedin_url=url)
            new_status = derive_contact_status(
                email=email,
                linkedin_url=url,
                rocketreach_status=contact.get("rocketreach_status"),
                linkedin_status=status,
            )
            payload = {
                "linkedin_status": status,
                "linkedin_url": url if status == "found" else contact.get("linkedin_url"),
                "preferred_channel": preferred,
                "status": new_status,
                "evidence": ev,
                "provenance": make_provenance(source="linkedin_find", lane="contacts"),
                "updated_at": utc_now_iso(),
            }
            if status == "found":
                payload["linkedin_url"] = li_url
            client.table("gtm_outreach_contacts").update(payload).eq(
                "id", contact_id
            ).execute()

    if person_id:
        existing = (
            client.table("gtm_clinic_people")
            .select("evidence")
            .eq("id", person_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if existing:
            ev = list(existing[0].get("evidence") or [])
            ev.append(
                evidence_item(
                    kind="linkedin_find",
                    value=result,
                    source="linkedin_find",
                    confidence=0.7 if status == "found" else 0.4,
                )
            )
            provenance = make_provenance(source="linkedin_find", lane="contacts")
            base = {
                "linkedin_status": status,
                "updated_at": utc_now_iso(),
                "evidence": ev,
                "provenance": provenance,
            }
            if status == "found":
                base["linkedin_url"] = li_url
            client.table("gtm_clinic_people").update(base).eq("id", person_id).execute()

    if status == "ambiguous":
        maybe_queue_match_review(
            entity_type="person_clinic",
            candidate={
                "linkedin_candidates": result.get("candidates"),
                "name": person_name,
            },
            target={
                "person_id": person_id,
                "contact_id": contact_id,
                "clinic_intelligence_id": clinic_intelligence_id,
                "clinic_name": clinic_name,
            },
            confidence=0.55,
            reasons=["multiple_linkedin_candidates"],
            clinic_intelligence_id=clinic_intelligence_id,
            clinic_account_id=clinic_account_id,
            dedupe_key=f"person_clinic:{contact_id or person_id}:linkedin",
            dry_run=False,
        )
    return entry


def find_and_apply_for_person(
    *,
    person_id: str | None,
    person_name: str,
    clinic_name: str = "",
    clinic_intelligence_id: str | None = None,
    clinic_account_id: str | None = None,
    dry_run: bool = False,
    contact_id: str | None = None,
) -> dict[str, Any]:
    result = search_linkedin_profile_url(person_name, clinic_name=clinic_name)
    return apply_linkedin_find_result(
        person_id=person_id,
        clinic_intelligence_id=clinic_intelligence_id,
        clinic_account_id=clinic_account_id,
        clinic_name=clinic_name,
        person_name=person_name,
        result=result,
        dry_run=dry_run,
        contact_id=contact_id,
    )


def linkedin_find_for_contacts(
    *,
    limit: int = 20,
    cohort: str | None = None,
    delay_s: float = 1.5,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Find LinkedIn for outreach contacts — everyone missing URL (even with email)."""
    if not supabase_configured():
        raise RuntimeError("Supabase not configured")

    from gtm_pipeline.segments import get_cohort, list_members

    clinic_filter: set[str] | None = None
    if cohort:
        if not get_cohort(cohort):
            raise ValueError(f"Unknown cohort: {cohort}")
        members = list_members(cohort, limit=5000)["members"]
        clinic_filter = {
            m["clinic_intelligence_id"] for m in members if m.get("clinic_intelligence_id")
        }

    client = get_client()
    rows = (
        client.table("gtm_outreach_contacts")
        .select("*")
        .order("founder_score", desc=True)
        .limit(max(limit * 5, limit))
        .execute()
        .data
        or []
    )

    stats: dict[str, Any] = {
        "attempted": 0,
        "found": 0,
        "ambiguous": 0,
        "none": 0,
        "failed": 0,
        "skipped": 0,
        "dry_run": dry_run,
        "cohort": cohort,
        "items": [],
    }

    for contact in rows:
        if clinic_filter is not None and contact["clinic_intelligence_id"] not in clinic_filter:
            continue
        if not force and (contact.get("linkedin_url") or "").strip():
            stats["skipped"] += 1
            continue
        if not force and (contact.get("linkedin_status") or "") == "found":
            stats["skipped"] += 1
            continue

        intel = (
            client.table("gtm_clinic_intelligence")
            .select("clinic_name")
            .eq("id", contact["clinic_intelligence_id"])
            .limit(1)
            .execute()
            .data
            or []
        )
        clinic_name = (intel[0].get("clinic_name") if intel else "") or ""

        stats["attempted"] += 1
        result = search_linkedin_profile_url(
            contact.get("full_name") or "",
            clinic_name=clinic_name,
        )
        status = result.get("status") or "none"
        entry = apply_linkedin_find_result(
            person_id=contact.get("person_id"),
            clinic_intelligence_id=contact["clinic_intelligence_id"],
            clinic_account_id=contact.get("clinic_account_id"),
            clinic_name=clinic_name,
            person_name=contact.get("full_name") or "",
            result=result,
            dry_run=dry_run,
            contact_id=contact["id"],
        )
        stats["items"].append(entry)
        stats[status] = stats.get(status, 0) + 1
        if len([i for i in stats["items"] if i.get("status") != "skipped"]) >= limit:
            # attempted already counted; stop after limit attempts
            pass
        if stats["attempted"] >= limit:
            break
        if delay_s:
            time.sleep(delay_s)

    return stats


def linkedin_find_for_cohort(
    slug: str,
    *,
    limit: int = 20,
    delay_s: float = 1.5,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Back-compat: LinkedIn find for a cohort via outreach contacts."""
    out = linkedin_find_for_contacts(
        limit=limit, cohort=slug, delay_s=delay_s, dry_run=dry_run
    )
    out["slug"] = slug
    return out
