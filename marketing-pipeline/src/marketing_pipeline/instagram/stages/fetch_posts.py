"""Fetch public Instagram posts for the DocMap account with Instaloader."""

from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path
from typing import Any

from marketing_pipeline import config


class InstaloaderNotInstalled(RuntimeError):
    """Raised when the optional instaloader dependency is missing."""


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "replace") and hasattr(value, "isoformat"):
        try:
            return value.replace(tzinfo=timezone.utc).isoformat()
        except TypeError:
            return value.isoformat()
    return str(value)


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _node_to_dict(node: Any) -> dict[str, Any]:
    return {
        "shortcode": getattr(node, "shortcode", None),
        "mediaid": str(getattr(node, "mediaid", "") or ""),
        "typename": getattr(node, "typename", None),
        "is_video": bool(getattr(node, "is_video", False)),
        "display_url": getattr(node, "display_url", None),
        "video_url": getattr(node, "video_url", None)
        if bool(getattr(node, "is_video", False))
        else None,
    }


def _post_to_dict(post: Any, *, include_comments: bool = False) -> dict[str, Any]:
    shortcode = getattr(post, "shortcode", None)
    child_media: list[dict[str, Any]] = []
    try:
        child_media = [_node_to_dict(node) for node in post.get_sidecar_nodes()]
    except Exception:  # noqa: BLE001
        child_media = []

    comments: list[dict[str, Any]] = []
    if include_comments:
        try:
            for comment in post.get_comments():
                comments.append(
                    {
                        "id": str(getattr(comment, "id", "") or ""),
                        "text": getattr(comment, "text", None),
                        "owner_username": getattr(getattr(comment, "owner", None), "username", None),
                        "created_at_utc": _iso(getattr(comment, "created_at_utc", None)),
                        "likes_count": _safe_int(getattr(comment, "likes_count", None)) or 0,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            comments = [{"error": f"comments_unavailable: {exc}"}]

    return {
        "mediaid": str(getattr(post, "mediaid", "") or ""),
        "shortcode": shortcode,
        "url": f"https://www.instagram.com/p/{shortcode}/" if shortcode else None,
        "typename": getattr(post, "typename", None),
        "product_type": getattr(post, "product_type", None),
        "is_video": bool(getattr(post, "is_video", False)),
        "date_utc": _iso(getattr(post, "date_utc", None)),
        "caption": getattr(post, "caption", None),
        "likes": _safe_int(getattr(post, "likes", None)),
        "comments": _safe_int(getattr(post, "comments", None)),
        "video_view_count": _safe_int(getattr(post, "video_view_count", None)),
        "video_duration": getattr(post, "video_duration", None),
        "display_url": getattr(post, "display_url", None),
        "video_url": getattr(post, "video_url", None)
        if bool(getattr(post, "is_video", False))
        else None,
        "child_media": child_media,
        "comments_sample": comments,
    }


def fetch_posts(
    *,
    account: str = config.INSTAGRAM_ACCOUNT,
    limit: int = 50,
    include_comments: bool = False,
    output_path: Path | None = None,
) -> dict[str, Any]:
    try:
        import instaloader  # type: ignore
    except ImportError as exc:
        raise InstaloaderNotInstalled(
            "Instaloader is not installed. Install with: pip install -e .[instagram]"
        ) from exc

    loader = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
    )
    profile = instaloader.Profile.from_username(loader.context, account)

    posts: list[dict[str, Any]] = []
    for index, post in enumerate(profile.get_posts()):
        if index >= limit:
            break
        posts.append(_post_to_dict(post, include_comments=include_comments))

    target = output_path or config.INSTAGRAM_RAW_DIR / f"{account}_posts.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "account": account,
        "source": "instaloader",
        "limit": limit,
        "include_comments": include_comments,
        "posts": posts,
    }
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"account": account, "posts": len(posts), "raw_path": str(target)}


def load_raw_posts(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or config.INSTAGRAM_RAW_DIR / f"{config.INSTAGRAM_ACCOUNT}_posts.json"
    if not target.exists():
        return []
    data = json.loads(target.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return list(data.get("posts") or [])
    if isinstance(data, list):
        return data
    return []

