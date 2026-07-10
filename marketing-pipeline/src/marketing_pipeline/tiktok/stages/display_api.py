"""TikTok Display API client for authenticated @docmap video metrics.

Requires Login Kit / Display API scopes: user.info.basic, video.list
(and user.info.stats if account totals are desired later).

Env:
  TIKTOK_CLIENT_KEY
  TIKTOK_CLIENT_SECRET
  TIKTOK_ACCESS_TOKEN
  TIKTOK_REFRESH_TOKEN  (optional; used to refresh access token)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from marketing_pipeline import config

logger = logging.getLogger(__name__)

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
VIDEO_LIST_URL = "https://open.tiktokapis.com/v2/video/list/"
VIDEO_QUERY_URL = "https://open.tiktokapis.com/v2/video/query/"

VIDEO_FIELDS = (
    "id,create_time,cover_image_url,share_url,video_description,duration,"
    "title,like_count,comment_count,share_count,view_count"
)


class DisplayApiError(RuntimeError):
    pass


class DisplayApiNotConfigured(DisplayApiError):
    pass


def _token_cache_path() -> Path:
    return config.ANALYSIS_DIR / "tiktok_display_tokens.json"


def load_tokens() -> dict[str, str]:
    """Merge env tokens with optional on-disk refresh cache."""
    access = config.TIKTOK_ACCESS_TOKEN
    refresh = config.TIKTOK_REFRESH_TOKEN
    cache = _token_cache_path()
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            access = data.get("access_token") or access
            refresh = data.get("refresh_token") or refresh
        except (json.JSONDecodeError, OSError):
            pass
    return {"access_token": access, "refresh_token": refresh}


def save_tokens(access_token: str, refresh_token: str | None = None) -> None:
    config.ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_tokens()
    payload = {
        "access_token": access_token,
        "refresh_token": refresh_token or existing.get("refresh_token") or "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _token_cache_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def require_configured() -> None:
    if not config.TIKTOK_CLIENT_KEY or not config.TIKTOK_CLIENT_SECRET:
        raise DisplayApiNotConfigured(
            "Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET for Display API"
        )
    tokens = load_tokens()
    if not tokens.get("access_token") and not tokens.get("refresh_token"):
        raise DisplayApiNotConfigured(
            "Set TIKTOK_ACCESS_TOKEN (and preferably TIKTOK_REFRESH_TOKEN)"
        )


def refresh_access_token() -> str:
    require_configured()
    tokens = load_tokens()
    refresh = tokens.get("refresh_token") or ""
    if not refresh:
        raise DisplayApiError("No refresh_token available; re-authorize Login Kit")

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            TOKEN_URL,
            data={
                "client_key": config.TIKTOK_CLIENT_KEY,
                "client_secret": config.TIKTOK_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        body = resp.json()

    data = body.get("data") or body
    access = data.get("access_token")
    if not access:
        raise DisplayApiError(f"Token refresh failed: {body}")
    new_refresh = data.get("refresh_token") or refresh
    save_tokens(access, new_refresh)
    return access


def _auth_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def _request_json(
    method: str,
    url: str,
    *,
    access_token: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with httpx.Client(timeout=45.0) as client:
        resp = client.request(
            method,
            url,
            params=params,
            json=json_body,
            headers=_auth_headers(access_token),
        )
        if resp.status_code == 401:
            access_token = refresh_access_token()
            resp = client.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=_auth_headers(access_token),
            )
        resp.raise_for_status()
        body = resp.json()

    err = body.get("error") or {}
    if err.get("code") and err.get("code") != "ok":
        raise DisplayApiError(f"Display API error: {err}")
    return body


def list_videos(*, max_count: int = 20, cursor: int | None = None) -> dict[str, Any]:
    """Paginated video list for the authenticated user."""
    require_configured()
    tokens = load_tokens()
    access = tokens.get("access_token") or refresh_access_token()
    body: dict[str, Any] = {"max_count": min(max_count, 20)}
    if cursor is not None:
        body["cursor"] = cursor
    return _request_json(
        "POST",
        f"{VIDEO_LIST_URL}?{urlencode({'fields': VIDEO_FIELDS})}",
        access_token=access,
        json_body=body,
    )


def iter_all_videos(*, page_size: int = 20, max_pages: int = 50) -> list[dict[str, Any]]:
    videos: list[dict[str, Any]] = []
    cursor: int | None = None
    for _ in range(max_pages):
        payload = list_videos(max_count=page_size, cursor=cursor)
        data = payload.get("data") or {}
        batch = data.get("videos") or []
        videos.extend(batch)
        if not data.get("has_more"):
            break
        cursor = data.get("cursor")
        if cursor is None:
            break
    return videos


def query_videos(video_ids: list[str]) -> list[dict[str, Any]]:
    """Refresh metrics for known IDs (max 20 per request)."""
    require_configured()
    if not video_ids:
        return []
    tokens = load_tokens()
    access = tokens.get("access_token") or refresh_access_token()
    out: list[dict[str, Any]] = []
    for i in range(0, len(video_ids), 20):
        chunk = video_ids[i : i + 20]
        payload = _request_json(
            "POST",
            f"{VIDEO_QUERY_URL}?{urlencode({'fields': VIDEO_FIELDS})}",
            access_token=access,
            json_body={"filters": {"video_ids": chunk}},
        )
        out.extend((payload.get("data") or {}).get("videos") or [])
    return out


def metrics_from_display_video(video: dict[str, Any]) -> dict[str, Any]:
    """Map Display API video object → our metrics JSONB (no saves)."""
    return {
        "views": int(video.get("view_count") or 0),
        "likes": int(video.get("like_count") or 0),
        "comments": int(video.get("comment_count") or 0),
        "shares": int(video.get("share_count") or 0),
        "duration_sec": int(video.get("duration") or 0) or None,
        # Display API does not expose saves
        "saves": None,
    }
