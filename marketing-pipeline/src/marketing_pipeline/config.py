"""Paths and environment for marketing-pipeline."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_PKG_DIR = Path(__file__).resolve().parent


def _getenv(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def _dev_package_root() -> Path:
    """marketing-pipeline/ when running from src layout."""
    return _PKG_DIR.parent.parent


def _resolve_data_root() -> Path:
    explicit = _getenv("MARKETING_DATA_DIR")
    if explicit:
        root = Path(explicit)
        root.mkdir(parents=True, exist_ok=True)
        return root

    dev_data = _dev_package_root() / "tiktok" / "data"
    if dev_data.is_dir():
        return dev_data

    # Railway / pip install: writable default (mount a volume here in prod)
    cache = Path("/app/marketing-data")
    cache.mkdir(parents=True, exist_ok=True)
    return cache


REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = _dev_package_root()
DATA_ROOT = _resolve_data_root()

# Account currently active for this process. Every path constant below is derived
# from it. `docmap` is the owned account; anything else is an observed peer
# library and must never share a data root with DocMap (see activate_account).
DEFAULT_ACCOUNT = "docmap"
ACCOUNT = DEFAULT_ACCOUNT
OWNED_ACCOUNTS = frozenset({"docmap"})
DOCMAP_DATA_ROOT = DATA_ROOT

load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(REPO_ROOT / ".env")

LEGACY_TIKTOK_ROOT = REPO_ROOT / "Social media analysis" / "tiktok_analysis"
LEGACY_SCRIPTS = LEGACY_TIKTOK_ROOT / "scripts"

TRANSCRIPTS_DIR = DATA_ROOT / "transcripts"
CATALOG_DIR = DATA_ROOT / "catalog"
COMMENTS_RAW_DIR = DATA_ROOT / "comments_raw"
ANALYSIS_DIR = DATA_ROOT / "analysis"
EXPORTS_DIR = DATA_ROOT / "exports"
MEDIA_DIR = DATA_ROOT / "media"
OCR_CACHE_DIR = DATA_ROOT / "ocr"
YT_META_DIR = DATA_ROOT / "yt_meta"
PLAYBOOKS_DIR = DATA_ROOT / "playbooks"
LEGACY_MEDIA_DIR = LEGACY_TIKTOK_ROOT / "audio"

MASTER_TRANSCRIPTS = TRANSCRIPTS_DIR / "ALL_COMPLETE_TRANSCRIPTS.txt"
DATASET_JSON = EXPORTS_DIR / "tiktok_marketing_dataset.json"
ALL_COMMENTS_TXT = EXPORTS_DIR / "ALL_COMMENTS.txt"
DATASET_VERSION = "2"
COMMENT_STALE_DAYS = 7

INSTAGRAM_ACCOUNT = _getenv("INSTAGRAM_ACCOUNT", default="docmapuk")
INSTAGRAM_DATA_ROOT = Path(
    _getenv(
        "MARKETING_INSTAGRAM_DATA_DIR",
        default=str(PACKAGE_ROOT / "instagram" / "data"),
    )
)
INSTAGRAM_RAW_DIR = INSTAGRAM_DATA_ROOT / "raw"
INSTAGRAM_COMMENTS_RAW_DIR = INSTAGRAM_DATA_ROOT / "comments_raw"
INSTAGRAM_ANALYSIS_DIR = INSTAGRAM_DATA_ROOT / "analysis"
INSTAGRAM_EXPORTS_DIR = INSTAGRAM_DATA_ROOT / "exports"
INSTAGRAM_MEDIA_DIR = INSTAGRAM_DATA_ROOT / "media"
INSTAGRAM_DATASET_JSON = INSTAGRAM_EXPORTS_DIR / "instagram_marketing_dataset.json"
INSTAGRAM_STRATEGY_BRIEF_JSON = INSTAGRAM_ANALYSIS_DIR / "instagram_strategy_brief.json"
INSTAGRAM_CONTENT_TRACKER_CSV = Path(
    _getenv(
        "INSTAGRAM_CONTENT_TRACKER_CSV",
        default=str(
            REPO_ROOT
            / "Social media analysis"
            / "Marketing - Content - Tracker - Content Tracker (3).csv"
        ),
    )
)


SUPABASE_URL = _getenv("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = _getenv("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY")
OPENROUTER_API_KEY = _getenv("OPENROUTER_API_KEY")
OPENROUTER_EMBEDDING_MODEL = _getenv(
    "OPENROUTER_EMBEDDING_MODEL", default="openai/text-embedding-3-small"
)
MODEL_OCR = _getenv("MODEL_OCR", default="google/gemini-3-flash-preview")
# Text LLM for video component cards (transcript/hook/CTA/funnel) — not vision OCR
MODEL_COMPONENTS = _getenv(
    "MODEL_COMPONENTS", default="deepseek/deepseek-v4-flash"
)
MODEL_CREATOR_CLASSIFY = _getenv(
    "MODEL_CREATOR_CLASSIFY", default=MODEL_COMPONENTS
)
FFMPEG_PATH = _getenv("FFMPEG_PATH", default="ffmpeg")
WHISPER_MODEL = _getenv("WHISPER_MODEL", default="small")


def _getint(name: str, default: int) -> int:
    raw = _getenv(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


# Cap CTranslate2 CPU threads. On high-core hosts (e.g. 8 vCPU) the default of
# "all cores" inflates memory per model. 4 is a safe balance for Whisper small.
WHISPER_CPU_THREADS = _getint("WHISPER_CPU_THREADS", 4)

# TikTok Display API (Login Kit) — velocity snapshots
TIKTOK_CLIENT_KEY = _getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = _getenv("TIKTOK_CLIENT_SECRET")
TIKTOK_ACCESS_TOKEN = _getenv("TIKTOK_ACCESS_TOKEN")
TIKTOK_REFRESH_TOKEN = _getenv("TIKTOK_REFRESH_TOKEN")

# Drop zone for Business Center / Studio CSV exports
BC_IMPORTS_DIR = Path(
    _getenv("TIKTOK_BC_IMPORTS_DIR", default=str(DATA_ROOT / "imports" / "business_center"))
)

# Studio Playwright listener — keep slow/small to avoid account risk
# Default: at most 12 videos, ~5s settle + ~10s pause between pages
STUDIO_LISTEN_RECENT = _getint("STUDIO_LISTEN_RECENT", 15)
STUDIO_LISTEN_SETTLE_MS = _getint("STUDIO_LISTEN_SETTLE_MS", 5000)
STUDIO_LISTEN_PAUSE_MS = _getint("STUDIO_LISTEN_PAUSE_MS", 10000)
STUDIO_LISTEN_PAUSE_JITTER_MS = _getint("STUDIO_LISTEN_PAUSE_JITTER_MS", 4000)
# Full-catalog baseline may take hours; keep pauses (don't zero them).
STUDIO_LISTEN_BASELINE_PAUSE_MS = _getint("STUDIO_LISTEN_BASELINE_PAUSE_MS", 8000)


# ---------------------------------------------------------------------------
# Account scoping
# ---------------------------------------------------------------------------
# Stages read paths as `config.CATALOG_DIR` (late-bound module attributes), so
# activating an account rebinds them in place and every stage follows without a
# signature change. Peer libraries get their own tree under peers/<handle>/ and
# are hard-blocked from resolving onto the DocMap data root.


class AccountIsolationError(RuntimeError):
    """Raised when a peer account would read or write DocMap's data root."""


_DATA_ROOT_DERIVED = (
    ("TRANSCRIPTS_DIR", "transcripts"),
    ("CATALOG_DIR", "catalog"),
    ("COMMENTS_RAW_DIR", "comments_raw"),
    ("ANALYSIS_DIR", "analysis"),
    ("EXPORTS_DIR", "exports"),
    ("MEDIA_DIR", "media"),
    ("OCR_CACHE_DIR", "ocr"),
    ("YT_META_DIR", "yt_meta"),
    ("PLAYBOOKS_DIR", "playbooks"),
)


def peer_data_root(handle: str) -> Path:
    """Data root for a peer library. Never inside the DocMap tree."""
    account_root = _getenv(f"MARKETING_PEER_DATA_DIR_{handle.upper()}")
    if account_root:
        return Path(account_root)
    parent_root = _getenv("MARKETING_PEER_DATA_DIR")
    if parent_root:
        return Path(parent_root) / handle
    return PACKAGE_ROOT / "peers" / handle


def _apply_data_root(root: Path) -> None:
    """Rebind every DATA_ROOT-derived path constant to `root`."""
    globals()["DATA_ROOT"] = root
    for name, leaf in _DATA_ROOT_DERIVED:
        globals()[name] = root / leaf
    globals()["MASTER_TRANSCRIPTS"] = root / "transcripts" / "ALL_COMPLETE_TRANSCRIPTS.txt"
    globals()["DATASET_JSON"] = root / "exports" / "tiktok_marketing_dataset.json"
    globals()["ALL_COMMENTS_TXT"] = root / "exports" / "ALL_COMMENTS.txt"
    globals()["BC_IMPORTS_DIR"] = root / "imports" / "business_center"
    globals()["SAMPLE_PLAN_JSON"] = root / "analysis" / "sample_plan.json"


def activate_account(handle: str | None) -> str:
    """Point this process at `handle`'s data tree. Returns the active handle.

    Raises AccountIsolationError if a peer account resolves onto the DocMap
    data root, which would mean writing peer media into the owned library.
    """
    handle = (handle or DEFAULT_ACCOUNT).strip().lstrip("@").lower()
    if not handle:
        raise AccountIsolationError("Account handle cannot be empty.")

    if handle in OWNED_ACCOUNTS:
        globals()["ACCOUNT"] = handle
        _apply_data_root(DOCMAP_DATA_ROOT)
        return handle

    root = peer_data_root(handle).resolve()
    docmap_root = Path(DOCMAP_DATA_ROOT).resolve()
    if root == docmap_root or docmap_root in root.parents:
        raise AccountIsolationError(
            f"Peer account '{handle}' resolved to the DocMap data root ({root}). "
            "Set MARKETING_PEER_DATA_DIR to a directory outside the DocMap tree."
        )
    root.mkdir(parents=True, exist_ok=True)
    globals()["ACCOUNT"] = handle
    _apply_data_root(root)
    return handle


def is_peer_account(handle: str | None = None) -> bool:
    return (handle or ACCOUNT) not in OWNED_ACCOUNTS


def owner_scope(handle: str | None = None) -> str:
    """Supabase owner_scope for the active account."""
    h = handle or ACCOUNT
    return h if h in OWNED_ACCOUNTS else f"peer:{h}"


def profile_url(handle: str | None = None) -> str:
    return f"https://www.tiktok.com/@{handle or ACCOUNT}"


def video_url(video_id: str, handle: str | None = None) -> str:
    return f"https://www.tiktok.com/@{handle or ACCOUNT}/video/{video_id}"


def catalog_filename(since: str, handle: str | None = None) -> str:
    return f"{handle or ACCOUNT}_catalog_since_{since.replace('-', '')}.json"


def catalog_glob(handle: str | None = None) -> str:
    return f"{handle or ACCOUNT}_catalog_since_*.json"


SAMPLE_PLAN_JSON = ANALYSIS_DIR / "sample_plan.json"
