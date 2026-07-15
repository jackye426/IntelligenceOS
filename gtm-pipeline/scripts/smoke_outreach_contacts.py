"""Smoke refresh outreach contacts from SoR."""

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
    from gtm_pipeline.contacts import list_outreach_contacts, refresh_outreach_contacts

    t0 = time.time()
    out = refresh_outreach_contacts(cqc_named_only=True, dry_run=False)
    print({"elapsed_s": round(time.time() - t0, 2), **out})
    ready = list_outreach_contacts(status="ready", limit=5)
    print({"ready_count": ready["count"], "sample": ready["contacts"][:3]})


if __name__ == "__main__":
    main()
