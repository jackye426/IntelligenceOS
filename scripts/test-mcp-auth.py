#!/usr/bin/env python3
"""Smoke test MCP auth + initialize."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env.local")

token = os.getenv("MCP_AUTH_TOKEN", "")
if not token:
    raise SystemExit("MCP_AUTH_TOKEN missing")

body = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"},
        },
    }
).encode()

req = urllib.request.Request(
    "http://127.0.0.1:8000/mcp",
    data=body,
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        print("status", resp.status)
        print(resp.read()[:500].decode("utf-8", errors="replace"))
except urllib.error.HTTPError as exc:
    print("status", exc.code)
    print(exc.read().decode("utf-8", errors="replace")[:500])
