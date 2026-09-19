"""Build and runtime provenance for MCP /health (tool surface fingerprint)."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

_REPO_ALLOWLIST_PREFIX = "synaptic-docmap/"


def tool_surface_fingerprint(tool_names: list[str]) -> str:
    payload = "\n".join(sorted(tool_names))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def parse_tool_names_from_source(source: str) -> list[str]:
    """MCP tools are ``def foo_tool(`` in main.py."""
    return sorted(re.findall(r"^def (\w+)_tool\(", source, re.MULTILINE))


def parse_tool_names_from_main_path(main_path: Path | None = None) -> list[str]:
    path = main_path or Path(__file__).resolve().parents[1] / "main.py"
    return parse_tool_names_from_source(path.read_text(encoding="utf-8"))


def tool_names_from_mcp(mcp_obj: Any) -> list[str]:
    try:
        manager = getattr(mcp_obj, "_tool_manager", None)
        if manager is not None and hasattr(manager, "list_tools"):
            tools = manager.list_tools()
            names = []
            for tool in tools:
                name = getattr(tool, "name", None) or getattr(tool, "title", None)
                if name:
                    names.append(str(name))
            if names:
                return sorted(names)
        tools_map = getattr(mcp_obj, "_tools", None)
        if isinstance(tools_map, dict) and tools_map:
            return sorted(str(k) for k in tools_map.keys())
    except Exception:
        pass
    return []


def _first_env(*keys: str) -> str:
    for key in keys:
        value = (os.getenv(key) or "").strip()
        if value:
            return value
    return "unknown"


def detect_platform() -> str:
    if (os.getenv("BUILD_GIT_COMMIT") or "").strip():
        return "aws-ecs"
    if (os.getenv("RAILWAY_SERVICE_NAME") or "").strip():
        return "railway"
    return "local"


def provenance(
    *,
    service: str,
    tool_names: list[str],
    admin_routes: bool = True,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    count = len(tool_names)
    fingerprint = tool_surface_fingerprint(tool_names) if tool_names else "unavailable"
    body: dict[str, Any] = {
        "status": "ok",
        "service": service,
        "platform": detect_platform(),
        "repo": _first_env("GITHUB_REPOSITORY", "RAILWAY_GIT_REPO"),
        "branch": _first_env("RAILWAY_GIT_BRANCH", "GITHUB_REF_NAME"),
        "commit": _first_env(
            "BUILD_GIT_COMMIT",
            "RAILWAY_GIT_COMMIT_SHA",
            "RAILWAY_GIT_COMMIT",
            "GITHUB_SHA",
        ),
        "deployment_id": _first_env("RAILWAY_DEPLOYMENT_ID"),
        "image_tag": os.getenv("BUILD_IMAGE_TAG", "") or "unknown",
        "tool_count": count,
        "tool_fingerprint": fingerprint,
        "admin_routes": admin_routes,
    }
    if body["repo"] != "unknown" and "/" not in body["repo"]:
        owner = _first_env("RAILWAY_GIT_REPO_OWNER")
        if owner != "unknown":
            body["repo"] = f"{owner}/{body['repo']}"
    if extra:
        body.update(extra)
    return body


def repo_is_org_allowed(repo: str) -> bool:
    if not repo or repo == "unknown":
        return False
    normalized = repo if "/" in repo else f"unknown/{repo}"
    return normalized.startswith(_REPO_ALLOWLIST_PREFIX)
