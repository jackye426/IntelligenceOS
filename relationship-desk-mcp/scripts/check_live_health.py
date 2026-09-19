#!/usr/bin/env python3
"""Post-deploy smoke test for relationship-desk MCP /health."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from common.build_provenance import repo_is_org_allowed  # noqa: E402

HOST = "https://email-mcp-production-bee8.up.railway.app"
LOCK_PATH = ROOT / "docs" / "TOOL_SURFACE.json"


def validate(health: dict, lock: dict) -> list[str]:
    errors: list[str] = []
    for key in ("tool_count", "tool_fingerprint", "platform", "repo", "commit", "service"):
        if key not in health:
            errors.append(f"missing key: {key}")
    repo = str(health.get("repo", "unknown"))
    if repo != "unknown" and not repo_is_org_allowed(repo):
        errors.append(f"repo does not match synaptic-docmap/*: {repo}")
    if health.get("tool_count") != lock.get("tool_count"):
        errors.append("tool_count mismatch")
    if health.get("tool_fingerprint") != lock.get("fingerprint"):
        errors.append("tool_fingerprint mismatch")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait", type=int, default=0)
    args = parser.parse_args()
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    deadline = time.time() + args.wait if args.wait else time.time()
    errors: list[str] = []
    while True:
        try:
            with urllib.request.urlopen(HOST.rstrip("/") + "/health", timeout=20) as resp:
                health = json.loads(resp.read().decode())
            errors = validate(health, lock)
            if not errors or time.time() >= deadline:
                break
        except Exception as exc:
            errors = [str(exc)]
            if time.time() >= deadline:
                break
        time.sleep(20)
    if errors:
        print("FAIL", HOST, "; ".join(errors))
        return 1
    print("OK", HOST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
