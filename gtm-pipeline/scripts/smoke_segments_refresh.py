"""Smoke: refresh outreach cohorts and print needs_contact counts."""

from __future__ import annotations

import os
import time
from pathlib import Path


def _load_env() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in (".env.local", ".env"):
        p = root / name
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def main() -> None:
    _load_env()
    from gtm_pipeline.segments import list_members, refresh_all_cohorts

    t0 = time.time()
    out = refresh_all_cohorts(dry_run=False)
    elapsed = time.time() - t0
    print({"elapsed_s": round(elapsed, 2), "refresh": out})
    for slug in ("solo_og_fertility", "needs_contact_priority", "small_derm"):
        m = list_members(slug, status="needs_contact", limit=500)
        print(
            {
                "slug": slug,
                "needs_contact": m["count"],
                "status_hint": "list capped at 500",
            }
        )


if __name__ == "__main__":
    main()
