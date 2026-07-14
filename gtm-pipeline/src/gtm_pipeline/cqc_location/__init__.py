"""CQC location Overview HTML scrape (requests + BeautifulSoup)."""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

import requests
from bs4 import BeautifulSoup

from gtm_pipeline.shared.provenance import evidence_item, make_provenance

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }
)


@dataclass
class CqcLocationOverview:
    location_id: str
    location_url: str
    name: str = ""
    registered_since: date | None = None
    specialisms: list[str] = field(default_factory=list)
    registered_manager: str = ""
    nominated_individual: str = ""
    provider_name: str = ""
    provider_url: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.registered_since:
            d["registered_since"] = self.registered_since.isoformat()
        return d


def _location_id_from_url(url: str) -> str:
    m = re.search(r"/location/([0-9\-]+)", url)
    return m.group(1) if m else ""


def _parse_registered_since(soup: BeautifulSoup) -> date | None:
    # "Registered on 1 May 2024"
    for h in soup.find_all(["h2", "h3", "p", "span"]):
        text = h.get_text(" ", strip=True)
        m = re.search(r"Registered\s+on\s+(\d{1,2}\s+\w+\s+\d{4})", text, re.I)
        if m:
            try:
                return datetime.strptime(m.group(1), "%d %B %Y").date()
            except ValueError:
                try:
                    return datetime.strptime(m.group(1), "%d %b %Y").date()
                except ValueError:
                    continue
    return None


def _parse_specialisms(soup: BeautifulSoup) -> list[str]:
    items: list[str] = []
    for li in soup.select("li.two-col__list-item--specialisms"):
        text = li.get_text(" ", strip=True)
        if text:
            items.append(text)
    return items


def _parse_who_runs(soup: BeautifulSoup) -> dict[str, str]:
    out = {
        "registered_manager": "",
        "nominated_individual": "",
        "provider_name": "",
        "provider_url": "",
    }

    # Provider: "The Luna Clinic is run by BBH Medical Solutions Ltd"
    for p in soup.select("p.two-col__title--who-runs-service"):
        text = p.get_text(" ", strip=True)
        m = re.search(r"is run by\s+(.+)$", text, re.I)
        if m:
            out["provider_name"] = m.group(1).strip()
            a = p.find("a", href=True)
            if a and "/provider/" in a["href"]:
                href = a["href"]
                out["provider_url"] = (
                    href if href.startswith("http") else f"https://www.cqc.org.uk{href}"
                )

    for p in soup.select("p.two-col__title--who-runs-service"):
        # Prefer structured <br/> split: "Name<br/>Registered Manager"
        parts = [t.strip() for t in p.stripped_strings]
        if len(parts) >= 2:
            name, role = parts[0], parts[1]
            if "Registered Manager" in role:
                out["registered_manager"] = name
                continue
            if "Nominated Individual" in role:
                out["nominated_individual"] = name
                continue

        text = p.get_text(" ", strip=True)
        if "Registered Manager" in text:
            out["registered_manager"] = text.replace("Registered Manager", "").strip()
        elif "Nominated Individual" in text:
            out["nominated_individual"] = text.replace("Nominated Individual", "").strip()

    # Fallback provider from header link
    if not out["provider_name"]:
        for a in soup.find_all("a", href=True):
            if "/provider/" in a["href"]:
                name = a.get_text(" ", strip=True)
                if name and len(name) > 2:
                    out["provider_name"] = name
                    href = a["href"]
                    out["provider_url"] = (
                        href if href.startswith("http") else f"https://www.cqc.org.uk{href}"
                    )
                    break

    return out


def parse_location_html(html: str, *, location_url: str = "") -> CqcLocationOverview:
    soup = BeautifulSoup(html, "lxml")
    location_id = _location_id_from_url(location_url)
    if not location_id:
        m = re.search(r"/location/([0-9\-]+)", html)
        location_id = m.group(1) if m else ""

    h1 = soup.find("h1")
    name = h1.get_text(" ", strip=True) if h1 else ""

    registered_since = _parse_registered_since(soup)
    specialisms = _parse_specialisms(soup)
    who = _parse_who_runs(soup)

    overview = CqcLocationOverview(
        location_id=location_id,
        location_url=location_url or (f"https://www.cqc.org.uk/location/{location_id}" if location_id else ""),
        name=name,
        registered_since=registered_since,
        specialisms=specialisms,
        registered_manager=who["registered_manager"],
        nominated_individual=who["nominated_individual"],
        provider_name=who["provider_name"],
        provider_url=who["provider_url"],
        provenance=make_provenance(
            source="cqc",
            source_url=location_url or None,
            lane="cqc_location",
            extractor="overview_html_v1",
        ),
    )
    overview.evidence.append(
        evidence_item(
            kind="cqc_who_runs",
            value={
                "registered_manager": overview.registered_manager,
                "nominated_individual": overview.nominated_individual,
                "provider_name": overview.provider_name,
            },
            source="cqc",
            source_url=overview.location_url,
        )
    )
    return overview


def fetch_location(location_url: str, *, timeout: int = 30) -> CqcLocationOverview:
    if not location_url.startswith("http"):
        location_url = f"https://www.cqc.org.uk/location/{location_url}"
    r = _SESSION.get(location_url, timeout=timeout)
    r.raise_for_status()
    return parse_location_html(r.text, location_url=location_url)
