"""Download / refresh the official CQC locations directory CSV.

Source: CQC transparency page → ``CQC_directory.csv`` (national dump).
Used as the local match index; does not call Clinic sales agent.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from gtm_pipeline import config

logger = logging.getLogger(__name__)

TRANSPARENCY_URL = "https://www.cqc.org.uk/about-us/transparency/using-cqc-data"
_CSV_HREF_RE = re.compile(
    r"https://www\.cqc\.org\.uk/sites/default/files/[^\"']*CQC_directory\.csv",
    re.I,
)

_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (compatible; DocMapGTM/0.1; +https://docmap.co) "
            "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
        ),
        "Accept": "text/html,application/octet-stream,*/*",
    }
)


@dataclass
class DirectoryStatus:
    path: str
    exists: bool
    size_bytes: int = 0
    age_days: float | None = None
    max_age_days: int = 7
    needs_refresh: bool = True
    refreshed: bool = False
    csv_url: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_directory_path() -> Path:
    """Prefer GTM data dir; fall back to env override via config."""
    return Path(config.CQC_DIRECTORY_PATH)


def max_age_days() -> int:
    raw = os.getenv("CQC_DIRECTORY_MAX_AGE_DAYS", "7").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 7


def find_directory_csv_url(*, session: requests.Session | None = None) -> str:
    sess = session or _SESSION
    r = sess.get(TRANSPARENCY_URL, timeout=30)
    r.raise_for_status()
    m = _CSV_HREF_RE.search(r.text)
    if not m:
        raise RuntimeError(
            "Could not find CQC_directory.csv URL on CQC transparency page"
        )
    return m.group(0)


def needs_refresh(path: Path | None = None, *, max_age: int | None = None) -> bool:
    path = path or default_directory_path()
    max_age = max_age if max_age is not None else max_age_days()
    if not path.exists() or path.stat().st_size < 1000:
        return True
    age = time.time() - path.stat().st_mtime
    return age >= max_age * 86400


def directory_status(path: Path | None = None) -> DirectoryStatus:
    path = path or default_directory_path()
    max_age = max_age_days()
    if not path.exists():
        return DirectoryStatus(
            path=str(path),
            exists=False,
            max_age_days=max_age,
            needs_refresh=True,
        )
    st = path.stat()
    age_days = (time.time() - st.st_mtime) / 86400.0
    return DirectoryStatus(
        path=str(path),
        exists=True,
        size_bytes=st.st_size,
        age_days=round(age_days, 2),
        max_age_days=max_age,
        needs_refresh=needs_refresh(path, max_age=max_age),
    )


def download_directory(
    dest: Path | None = None,
    *,
    force: bool = False,
) -> DirectoryStatus:
    """Download CQC directory CSV if missing/stale (or ``force``)."""
    dest = dest or default_directory_path()
    status = directory_status(dest)
    if not force and not status.needs_refresh:
        status.refreshed = False
        return status

    try:
        url = find_directory_csv_url()
        status.csv_url = url
        logger.info("Downloading CQC directory from %s → %s", url, dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Write to temp then replace so a failed download does not wipe a good file
        tmp = dest.with_suffix(dest.suffix + ".partial")
        with _SESSION.get(url, timeout=180, stream=True) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
        if tmp.stat().st_size < 1000:
            tmp.unlink(missing_ok=True)
            raise RuntimeError("Downloaded CQC directory looks empty")
        tmp.replace(dest)
        # Invalidate in-memory match cache
        from gtm_pipeline.cqc_directory import clear_directory_cache

        clear_directory_cache()
        status = directory_status(dest)
        status.refreshed = True
        status.csv_url = url
        logger.info(
            "CQC directory ready: %.1f MB age=%.2fd",
            status.size_bytes / (1024 * 1024),
            status.age_days or 0,
        )
        return status
    except Exception as exc:
        logger.exception("CQC directory refresh failed")
        status.error = str(exc)
        status.refreshed = False
        # Keep existing file usable if present
        if dest.exists():
            status.exists = True
            status.needs_refresh = True
        return status


def ensure_directory(
    path: Path | None = None,
    *,
    force: bool = False,
    raise_on_error: bool = False,
) -> Path:
    """Ensure directory CSV exists (download if needed). Returns path."""
    path = path or default_directory_path()
    status = download_directory(path, force=force)
    if not path.exists():
        msg = status.error or f"CQC directory missing at {path}"
        if raise_on_error:
            raise FileNotFoundError(msg)
        raise FileNotFoundError(msg)
    if status.error and raise_on_error and status.needs_refresh and force:
        raise RuntimeError(status.error)
    return path


def iso_mtime(path: Path | None = None) -> str | None:
    path = path or default_directory_path()
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
