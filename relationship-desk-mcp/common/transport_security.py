"""MCP transport security for Relationship Desk."""

from __future__ import annotations

from mcp.server.transport_security import TransportSecuritySettings

from . import config

_DEFAULT_ALLOWED_HOSTS = [
    "127.0.0.1",
    "127.0.0.1:*",
    "localhost",
    "localhost:*",
    "[::1]",
    "[::1]:*",
]


def _expand_hosts(hosts: list[str]) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()
    for host in hosts:
        candidates = (host, f"{host}:443") if ":" not in host else (host,)
        for candidate in candidates:
            if candidate not in seen:
                expanded.append(candidate)
                seen.add(candidate)
    return expanded


def build_transport_security() -> TransportSecuritySettings:
    if not config.DNS_REBINDING_PROTECTION:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_expand_hosts(config.ALLOWED_HOSTS or _DEFAULT_ALLOWED_HOSTS),
        allowed_origins=config.ALLOWED_ORIGINS,
    )

