"""Authentication middleware for hosted MCP."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import config


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in {"/health", "/"}:
            return await call_next(request)

        if not config.MCP_AUTH_TOKEN:
            return JSONResponse(
                {"error": "MCP_AUTH_TOKEN is not configured"},
                status_code=503,
            )

        auth_header = request.headers.get("authorization", "")
        token_header = request.headers.get("x-mcp-auth", "")
        expected = f"Bearer {config.MCP_AUTH_TOKEN}"
        token = config.MCP_AUTH_TOKEN.strip()
        if (
            auth_header.strip() != expected
            and auth_header.strip() != f"Bearer {token}"
            and token_header.strip() != token
        ):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        origin = request.headers.get("origin")
        if origin and config.MCP_ALLOWED_ORIGINS and origin not in config.MCP_ALLOWED_ORIGINS:
            return JSONResponse({"error": "Origin not allowed"}, status_code=403)

        return await call_next(request)
