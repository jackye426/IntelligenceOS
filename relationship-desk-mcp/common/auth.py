"""Authentication middleware for Relationship Desk."""

from __future__ import annotations

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import config


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in {"/health", "/"}:
            return await call_next(request)

        if not config.AUTH_TOKEN:
            return JSONResponse(
                {"error": "RELATIONSHIP_DESK_AUTH_TOKEN is not configured"},
                status_code=503,
            )

        token = config.AUTH_TOKEN.strip()
        auth_header = request.headers.get("authorization", "")
        token_header = request.headers.get("x-relationship-desk-auth", "").strip()
        bearer = auth_header.strip()
        bearer_ok = bearer and token and (
            hmac.compare_digest(bearer, f"Bearer {token}")
            or hmac.compare_digest(bearer, token)
        )
        header_ok = (
            len(token_header) == len(token)
            and bool(token)
            and hmac.compare_digest(token_header, token)
        )
        if not (bearer_ok or header_ok):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        origin = request.headers.get("origin")
        if origin and config.ALLOWED_ORIGINS and origin not in config.ALLOWED_ORIGINS:
            return JSONResponse({"error": "Origin not allowed"}, status_code=403)

        return await call_next(request)

