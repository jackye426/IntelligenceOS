"""Fetch public Instagram posts for the DocMap account with Instaloader."""

from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path
from typing import Any

from marketing_pipeline import config


class InstaloaderNotInstalled(RuntimeError):
    """Raised when the optional instaloader dependency is missing."""


def session_path(account: str | None = None) -> Path:
    """Instaloader session file path expected by data-worker + fetch."""
    handle = (account or config.INSTAGRAM_ACCOUNT).lstrip("@")
    return config.INSTAGRAM_DATA_ROOT / f"session-{handle}"


def _make_loader():
    try:
        import instaloader  # type: ignore
    except ImportError as exc:
        raise InstaloaderNotInstalled(
            "Instaloader is not installed. Install with: pip install -e .[instagram]"
        ) from exc

    return instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
    )


def login_and_save_session(
    *,
    account: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    """Interactive Instaloader login; writes session-{account} under INSTAGRAM_DATA_ROOT.

    Prefer logging in as @docmapuk so the file is named session-docmapuk (what Railway expects).
    Supports Instagram 2FA prompts via interactive_login when password is omitted.
    """
    handle = (account or config.INSTAGRAM_ACCOUNT).lstrip("@")
    target = session_path(handle)
    target.parent.mkdir(parents=True, exist_ok=True)

    loader = _make_loader()
    try:
        if password:
            loader.login(handle, password)
        else:
            # Prompts for password / 2FA in the terminal
            loader.interactive_login(handle)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        # Instagram often returns a relative checkpoint path — make it clickable.
        if "Checkpoint required" in msg or "checkpoint" in msg.lower():
            marker = "Point your browser to "
            if marker in msg:
                rel = msg.split(marker, 1)[1].split(" - follow", 1)[0].strip()
                if rel.startswith("/"):
                    url = f"https://www.instagram.com{rel}"
                elif rel.startswith("http"):
                    url = rel
                else:
                    url = f"https://www.instagram.com/{rel.lstrip('/')}"
                raise RuntimeError(
                    "Instagram requires a security checkpoint before Instaloader can log in.\n"
                    f"1. Open this URL in a browser (same machine / logged-in if possible):\n   {url}\n"
                    "2. Complete the challenge (approve login / confirm it's you).\n"
                    "3. Re-run: python -m marketing_pipeline instagram login --account docmapuk\n"
                    "Tip: first log into Instagram normally in Chrome as @docmapuk, then retry."
                ) from exc
        raise

    # Instaloader writes session-{username} into the given directory
    loader.save_session_to_file(str(target))
    if not target.exists():
        # Some versions append nothing; others may write beside the path — normalize.
        raise FileNotFoundError(f"Instaloader did not write session file at {target}")

    return {
        "account": handle,
        "session_path": str(target),
        "note": "Copy this file to Railway volume: $MARKETING_DATA_DIR/instagram/session-docmapuk",
    }


def _load_session(loader: Any, account: str) -> bool:
    """Load session-{account} if present. Returns True when loaded."""
    path = session_path(account)
    if not path.exists():
        return False
    loader.load_session_from_file(account, str(path))
    return True


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
    import instaloader  # type: ignore  # noqa: F401 — validated via _make_loader

    handle = account.lstrip("@")
    loader = _make_loader()
    session_loaded = _load_session(loader, handle)
    if not session_loaded:
        raise FileNotFoundError(
            f"No Instaloader session at {session_path(handle)}. "
            f"Run: python -m marketing_pipeline instagram login --account {handle}"
        )

    profile = instaloader.Profile.from_username(loader.context, handle)

    posts: list[dict[str, Any]] = []
    for index, post in enumerate(profile.get_posts()):
        if index >= limit:
            break
        posts.append(_post_to_dict(post, include_comments=include_comments))

    target = output_path or config.INSTAGRAM_RAW_DIR / f"{handle}_posts.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "account": handle,
        "source": "instaloader",
        "limit": limit,
        "include_comments": include_comments,
        "session_loaded": session_loaded,
        "posts": posts,
    }
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "account": handle,
        "posts": len(posts),
        "raw_path": str(target),
        "session_loaded": session_loaded,
    }

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

