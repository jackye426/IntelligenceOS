"""MCP streamable-HTTP transport security for reverse-proxy / Railway deploys."""

from __future__ import annotations

from mcp.server.transport_security import TransportSecuritySettings

from . import config

# Local dev defaults — MCP SDK 1.26+ rejects non-local Host on POST without these.
_DEFAULT_ALLOWED_HOSTS = [
    "127.0.0.1",
    "127.0.0.1:*",
    "localhost",
    "localhost:*",
    "[::1]",
    "[::1]:*",
    "mcp.docmap.co.uk",
    "mcp.docmap.co.uk:443",
    "intelligenceos-production.up.railway.app",
    "intelligenceos-production.up.railway.app:443",
]


def _expand_hosts(hosts: list[str]) -> list[str]:
    """Add :443 variants so Railway/custom-domain POST /mcp is accepted."""
    expanded: list[str] = []
    seen: set[str] = set()
    for host in hosts:
        for candidate in (host, f"{host}:443") if ":" not in host else (host,):
            if candidate not in seen:
                seen.add(candidate)
                expanded.append(candidate)
    return expanded


def build_transport_security() -> TransportSecuritySettings:
    """
    Configure DNS rebinding protection for hosted MCP.

    Without allowed_hosts, MCP SDK 1.26+ returns 421 Invalid Host header on POST
    /mcp when accessed via mcp.docmap.co.uk (GET /health still works).
    """
    if not config.MCP_DNS_REBINDING_PROTECTION:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)

    hosts = config.MCP_ALLOWED_HOSTS or _DEFAULT_ALLOWED_HOSTS
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_expand_hosts(hosts),
        allowed_origins=config.MCP_ALLOWED_ORIGINS,
    )
