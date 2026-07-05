#!/usr/bin/env python3
"""Test hosted MCP endpoints."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env.local")

token = os.getenv("MCP_AUTH_TOKEN", "")
init_body = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "claude", "version": "1.0"},
        },
    }
).encode()


def probe(label: str, url: str, body: bytes) -> None:
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            print(f"{label}: OK {resp.status}")
            print(resp.read()[:400].decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        print(f"{label}: HTTP {exc.code}")
        print(exc.read()[:200].decode("utf-8", errors="replace"))


if __name__ == "__main__":
    base = "https://mcp.docmap.co.uk/mcp"
    probe("empty body", base, b"{}")
    probe("initialize", base, init_body)
