"""Logged-out TikTok profile HTML GET + rehydration parse."""

from __future__ import annotations

import gzip
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from marketing_pipeline.creators import ratelimit
from marketing_pipeline.creators.paths import normalise_handle, profile_cache_dir

REHYDRATION_RE = re.compile(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
    re.S,
)

DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

BLOCK_MARKERS = ("captcha", "verify to continue", "access denied")


class ProfileFetchError(RuntimeError):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind  # block | unavailable | parse


def _cache_path(handle: str) -> Path:
    return profile_cache_dir() / f"{handle}.html.gz"


def extract_rehydration(html: str) -> dict[str, Any]:
    match = REHYDRATION_RE.search(html)
    if not match:
        lower = html.lower()
        if any(m in lower for m in BLOCK_MARKERS):
            raise ProfileFetchError("block", "captcha or challenge page")
        raise ProfileFetchError("block", "missing __UNIVERSAL_DATA_FOR_REHYDRATION__")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ProfileFetchError("parse", f"rehydration JSON invalid: {exc}") from exc


def user_info_from_blob(blob: dict[str, Any]) -> dict[str, Any]:
    user_detail = (
        blob.get("__DEFAULT_SCOPE__", {})
        .get("webapp.user-detail", {})
    )
    if not user_detail:
        # some payloads nest under defaultScope
        user_detail = blob.get("webapp.user-detail") or {}
    status = user_detail.get("statusCode")
    if status in (10202, 10221):
        raise ProfileFetchError("unavailable", f"statusCode={status}")
    info = (user_detail.get("userInfo") or {}).get("user") or {}
    stats = (user_detail.get("userInfo") or {}).get("stats") or {}
    if status not in (None, 0) and not info:
        raise ProfileFetchError("unavailable", f"statusCode={status}")
    if not info:
        raise ProfileFetchError("block", "userInfo missing")
    return {"user": info, "stats": stats, "statusCode": status or 0}


def profile_fields(info: dict[str, Any]) -> dict[str, Any]:
    user = info["user"]
    stats = info.get("stats") or {}
    handle = normalise_handle(user.get("uniqueId") or user.get("unique_id") or "")
    created = user.get("createTime") or user.get("create_time")
    created_at = None
    if created:
        created_at = datetime.fromtimestamp(int(created), tz=timezone.utc).isoformat()
    private = bool(user.get("privateAccount") or user.get("secret"))
    bio_link = None
    link = user.get("bioLink") or {}
    if isinstance(link, dict):
        bio_link = link.get("link")
    return {
        "tiktok_user_id": str(user.get("id") or user.get("uid") or ""),
        "sec_uid": user.get("secUid") or user.get("sec_uid"),
        "handle": handle,
        "profile_url": f"https://www.tiktok.com/@{handle}" if handle else None,
        "nickname": user.get("nickname"),
        "bio": user.get("signature"),
        "bio_link": bio_link,
        "follower_count": stats.get("followerCount") or user.get("followerCount"),
        "following_count": stats.get("followingCount"),
        "heart_count": stats.get("heartCount") or stats.get("heart"),
        "video_count": stats.get("videoCount"),
        "verified": user.get("verified"),
        "is_organization": user.get("isOrganization"),
        "commerce_user": (user.get("commerceUserInfo") or {}).get("commerceUser"),
        "tt_seller": user.get("ttSeller"),
        "language": user.get("language"),
        "private_account": private,
        "account_created_at": created_at,
    }


def fetch_profile_html(handle: str, *, client: httpx.Client | None = None, timeout: float = 20.0) -> str:
    handle = normalise_handle(handle)
    ratelimit.PROFILE_HTML.acquire()
    own = client is None
    http = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        resp = http.get(
            f"https://www.tiktok.com/@{handle}",
            headers={
                "User-Agent": DESKTOP_UA,
                "Accept-Language": "en-GB,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        if resp.status_code in (403, 429):
            raise ProfileFetchError("block", f"HTTP {resp.status_code}")
        if resp.status_code >= 500:
            raise ProfileFetchError("block", f"HTTP {resp.status_code}")
        html = resp.text
        cache = _cache_path(handle)
        cache.write_bytes(gzip.compress(html.encode("utf-8")))
        return html
    finally:
        if own:
            http.close()
