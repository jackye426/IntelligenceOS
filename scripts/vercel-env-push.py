#!/usr/bin/env python3
"""Push required app env vars from .env.local to Vercel production (no stdout secrets)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.local"

# App-only — not MCP/worker vars
KEYS = [
    "NEXT_PUBLIC_SUPABASE_URL",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
    "OPENROUTER_EMBEDDING_MODEL",
    "SESSION_PASSWORD",
    "INTERNAL_PASSWORD",
    "SUPABASE_PRACTITIONERS_TABLE",
]


def parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k, v = k.strip(), v.strip()
        if k == "VERCEL_OIDC_TOKEN":
            continue
        if v:
            out[k] = v
    return out


def _vercel_cmd(*args: str) -> list[str]:
    return ["npx.cmd", "--yes", "vercel@latest", *args]


def push(name: str, value: str) -> None:
    subprocess.run(
        _vercel_cmd("env", "rm", name, "production", "--yes"),
        cwd=ROOT,
        capture_output=True,
        text=True,
        shell=False,
    )
    proc = subprocess.run(
        _vercel_cmd("env", "add", name, "production"),
        cwd=ROOT,
        input=value + "\n",
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        print(f"FAIL {name}: {proc.stderr.strip() or proc.stdout.strip()}", file=sys.stderr)
        sys.exit(1)
    print(f"OK {name}")


def main() -> None:
    env = parse_env(ENV_FILE)
    missing = [k for k in KEYS if k not in env or not env[k]]
    # SUPABASE_SERVICE_ROLE_KEY optional if SUPABASE_KEY set
    missing = [k for k in missing if k != "SUPABASE_SERVICE_ROLE_KEY"]
    if missing:
        print(f"Missing in .env.local: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    for key in KEYS:
        val = env.get(key, "")
        if not val:
            continue
        push(key, val)
    print("Vercel production env synced.")


if __name__ == "__main__":
    main()
