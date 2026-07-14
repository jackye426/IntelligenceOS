"""Discover carousel PNG templates from repo-root templates/ folder."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from common import config

TEMPLATES_ROOT = config.REPO_ROOT / "templates"
ZONES_PATH = Path(__file__).resolve().parent / "template_zones.json"
SLIDE_W_IN = 10.0
SLIDE_H_IN = 12.5
PNG_W = 1080
PNG_H = 1350

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_NUM_SUFFIX_RE = re.compile(r"-(\d+)\.png$", re.IGNORECASE)


def _slugify(name: str) -> str:
    s = _SLUG_RE.sub("_", name.strip().lower()).strip("_")
    return s or "template"


def _slide_number(path: Path) -> int:
    m = _NUM_SUFFIX_RE.search(path.name)
    return int(m.group(1)) if m else 0


@lru_cache(maxsize=1)
def _load_zone_config() -> dict[str, Any]:
    return json.loads(ZONES_PATH.read_text(encoding="utf-8"))


def discover_template_sets() -> list[dict[str, Any]]:
    """Scan templates/ for subfolders containing numbered PNG slides."""
    if not TEMPLATES_ROOT.is_dir():
        return []

    sets: list[dict[str, Any]] = []
    zone_cfg = _load_zone_config()

    for folder in sorted(TEMPLATES_ROOT.iterdir()):
        if not folder.is_dir():
            continue
        pngs = sorted(
            folder.rglob("*.png"),
            key=lambda p: (_slide_number(p), p.name),
        )
        if not pngs:
            continue

        template_id = _slugify(folder.name)
        meta = zone_cfg.get("templates", {}).get(template_id, {})
        slide_count = len(pngs)
        body_slots = max(0, slide_count - 2)

        sets.append(
            {
                "id": template_id,
                "name": meta.get("name") or folder.name.replace("_", " ").title(),
                "description": meta.get("description", f"{slide_count}-slide carousel template."),
                "best_for": meta.get("best_for", []),
                "folder": str(folder.relative_to(config.REPO_ROOT)).replace("\\", "/"),
                "slide_count": slide_count,
                "body_slide_slots": body_slots,
                "slides": [
                    {
                        "index": i + 1,
                        "png_path": str(p.relative_to(config.REPO_ROOT)).replace("\\", "/"),
                        "role": _role_for_index(i, slide_count),
                    }
                    for i, p in enumerate(pngs)
                ],
            }
        )
    return sets


def _role_for_index(i: int, total: int) -> str:
    if i == 0:
        return "hook"
    if i == total - 1:
        return "cta"
    return "body"


def get_template_set(template_id: str) -> dict[str, Any]:
    for t in discover_template_sets():
        if t["id"] == template_id:
            return t
    known = [t["id"] for t in discover_template_sets()]
    raise ValueError(f"Unknown template_id={template_id!r}. Known: {known}")


def get_zone_preset(template_id: str, role: str) -> dict[str, Any]:
    cfg = _load_zone_config()
    templates = cfg.get("templates") or {}
    t = templates.get(template_id) or {}
    presets = t.get("zone_presets") or {}
    if role in presets:
        return presets[role]
    # fallback to default presets
    defaults = cfg.get("defaults", {}).get("zone_presets") or {}
    if role in defaults:
        return defaults[role]
    raise ValueError(f"No zone preset for template={template_id!r} role={role!r}")


def png_to_inches(px_x: float, px_y: float, px_w: float, px_h: float) -> tuple[float, float, float, float]:
    return (
        (px_x / PNG_W) * SLIDE_W_IN,
        (px_y / PNG_H) * SLIDE_H_IN,
        (px_w / PNG_W) * SLIDE_W_IN,
        (px_h / PNG_H) * SLIDE_H_IN,
    )


def list_templates_for_mcp() -> list[dict[str, Any]]:
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "description": t["description"],
            "best_for": t["best_for"],
            "slide_count": t["slide_count"],
            "body_slide_slots": t["body_slide_slots"],
        }
        for t in discover_template_sets()
    ]
