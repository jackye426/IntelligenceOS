"""CQC directory matching with numeric confidence + multi-candidate."""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from gtm_pipeline import config
from gtm_pipeline.shared.address import normalise_postcode
from gtm_pipeline.shared.match_confidence import match_confidence
from gtm_pipeline.shared.name import normalise_name

logger = logging.getLogger(__name__)

_DIR_CACHE: pd.DataFrame | None = None
_DIR_CACHE_PATH: Path | None = None


def clear_directory_cache() -> None:
    global _DIR_CACHE, _DIR_CACHE_PATH
    _DIR_CACHE = None
    _DIR_CACHE_PATH = None


@dataclass
class CqcDirectoryCandidate:
    name: str
    postcode: str
    phone: str
    website: str
    location_url: str
    location_id: str
    provider_name: str
    address: str
    specialisms: str
    confidence: float
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_directory(path: Path | None = None, *, auto_refresh: bool = True) -> pd.DataFrame:
    global _DIR_CACHE, _DIR_CACHE_PATH
    path = path or config.CQC_DIRECTORY_PATH

    if auto_refresh:
        from gtm_pipeline.cqc_directory.refresh import ensure_directory

        try:
            path = ensure_directory(path, raise_on_error=False)
        except FileNotFoundError:
            pass

    if (
        _DIR_CACHE is not None
        and _DIR_CACHE_PATH is not None
        and path.resolve() == _DIR_CACHE_PATH.resolve()
    ):
        return _DIR_CACHE

    if not path.exists():
        raise FileNotFoundError(
            f"CQC directory CSV not found at {path}. "
            "Run `python -m gtm_pipeline cqc refresh-directory` or set CQC_DIRECTORY_PATH."
        )

    # Official CQC CSV has 4 preamble rows before the header.
    df = pd.read_csv(path, encoding="latin-1", skiprows=4, dtype=str)
    df = df.fillna("")
    df["_name_norm"] = df["Name"].map(normalise_name)
    df["_postcode_norm"] = df["Postcode"].map(normalise_postcode)
    _DIR_CACHE = df
    _DIR_CACHE_PATH = path.resolve()
    return df


def _row_to_candidate(row: dict[str, Any], confidence: float, reasons: list[str]) -> CqcDirectoryCandidate:
    return CqcDirectoryCandidate(
        name=str(row.get("Name") or ""),
        postcode=normalise_postcode(row.get("Postcode")),
        phone=str(row.get("Phone number") or ""),
        website=str(row.get("Service's website (if available)") or ""),
        location_url=str(row.get("Location URL") or ""),
        location_id=str(row.get("CQC Location ID (for office use only)") or ""),
        provider_name=str(row.get("Provider name") or ""),
        address=str(row.get("Address") or ""),
        specialisms=str(row.get("Specialisms/services") or ""),
        confidence=confidence,
        reasons=reasons,
    )


def match_directory(
    *,
    name: str,
    postcode: str = "",
    address: str = "",
    website: str = "",
    phone: str = "",
    path: Path | None = None,
    top_k: int = 5,
) -> list[CqcDirectoryCandidate]:
    """Return ranked CQC directory candidates with numeric confidence.

    Always includes a name-narrowed pool (so a wrong Doctify postcode cannot hide
    the real clinic) and, when ``website`` is set, a hostname pool.
    """
    from urllib.parse import urlparse

    df = _load_directory(path)
    target = {
        "name": name,
        "postcode": postcode or address,
        "address": address,
        "website": website,
        "phone": phone,
    }

    def _host(url: str) -> str:
        if not url:
            return ""
        try:
            parsed = urlparse(url if "://" in url else f"https://{url}")
        except ValueError:
            return ""
        return parsed.netloc.lower().removeprefix("www.")

    pc = normalise_postcode(postcode or address)
    pools: list[pd.DataFrame] = []
    if pc:
        exact = df[df["_postcode_norm"] == pc]
        if not exact.empty:
            pools.append(exact)
        else:
            outward = pc.split(" ")[0]
            prefix = df[df["_postcode_norm"].str.startswith(outward, na=False)]
            if not prefix.empty:
                pools.append(prefix)

    # Always include a name-narrowed pool so a wrong/nearby postcode cannot hide the real clinic.
    norm = normalise_name(name)
    name_pool = df
    if len(norm) >= 3:
        first = norm.split()[0]
        mask = df["_name_norm"].str.contains(re.escape(first), na=False)
        narrowed = df[mask]
        if not narrowed.empty:
            name_pool = narrowed if len(narrowed) <= 5000 else narrowed.head(2000)
    pools.append(name_pool)

    # Website hostname pool (independent of geo / name tokens)
    host = _host(website)
    if host:
        web_col = "Service's website (if available)"
        if "_web_host" not in df.columns:
            df = df.copy()
            df["_web_host"] = df[web_col].map(_host)
        web_pool = df[df["_web_host"] == host]
        if web_pool.empty and host.count(".") >= 2:
            parent = ".".join(host.split(".")[-2:])
            web_pool = df[df["_web_host"] == parent]
        if not web_pool.empty:
            pools.append(web_pool)

    # Merge pools without duplicate index rows
    pool = pd.concat(pools).drop_duplicates()
    if len(pool) > 3000:
        pool = pool.head(3000)

    scored: list[CqcDirectoryCandidate] = []
    for _, row in pool.iterrows():
        candidate = {
            "name": row.get("Name"),
            "postcode": row.get("Postcode"),
            "address": row.get("Address"),
            "website": row.get("Service's website (if available)"),
            "phone": row.get("Phone number"),
        }
        result = match_confidence(candidate, target)
        if result.confidence < 0.35:
            continue
        # Prefer exact (casefold) clinic name when scores otherwise tie.
        if (row.get("Name") or "").strip().casefold() == name.strip().casefold():
            result.confidence = round(min(1.0, result.confidence + 0.05), 4)
            result.reasons.append("exact_name_bonus=+0.05")
        scored.append(_row_to_candidate(row.to_dict(), result.confidence, result.reasons))

    scored.sort(key=lambda c: c.confidence, reverse=True)
    # Dedupe by location_id
    seen: set[str] = set()
    unique: list[CqcDirectoryCandidate] = []
    for c in scored:
        key = c.location_id or c.location_url or c.name
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)
        if len(unique) >= top_k:
            break
    return unique


def best_match(**kwargs: Any) -> CqcDirectoryCandidate | None:
    hits = match_directory(**kwargs, top_k=1)
    return hits[0] if hits else None
