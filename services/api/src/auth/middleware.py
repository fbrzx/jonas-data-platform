"""Token → user + tenant resolution middleware.

When DEMO_MODE=true (default for local dev), the three hardcoded demo tokens
(admin-token, analyst-token, viewer-token) are accepted alongside real JWTs.
In production set DEMO_MODE=false to require JWT auth only.
"""

from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

# Paths that don't require authentication
PUBLIC_PATHS = {
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/accept-invite",
}

_DEMO_TOKENS: dict[str, dict[str, Any]] = {
    "owner-token": {
        "user_id": "user-owner",
        "email": "owner@acme.io",
        "tenant_id": "tenant-acme",
        "role": "owner",
    },
    "admin-token": {
        "user_id": "user-admin",
        "email": "admin@acme.io",
        "tenant_id": "tenant-acme",
        "role": "admin",
    },
    "engineer-token": {
        "user_id": "user-engineer",
        "email": "engineer@acme.io",
        "tenant_id": "tenant-acme",
        "role": "engineer",
    },
    "analyst-token": {
        "user_id": "user-analyst",
        "email": "analyst@acme.io",
        "tenant_id": "tenant-acme",
        "role": "analyst",
    },
    "viewer-token": {
        "user_id": "user-viewer",
        "email": "viewer@acme.io",
        "tenant_id": "tenant-acme",
        "role": "viewer",
    },
}


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        from src.config import settings

        self._demo_mode = settings.demo_mode

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        token = self._extract_token(request)
        request.state.user = self._resolve_token(token) if token else None
        return await call_next(request)

    @staticmethod
    def _extract_token(request: Request) -> str | None:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[len("Bearer ") :]
        return request.headers.get("X-API-Token")

    def _resolve_token(self, token: str) -> dict[str, Any]:
        # Demo tokens — only when DEMO_MODE=true
        if self._demo_mode and token in _DEMO_TOKENS:
            return _DEMO_TOKENS[token]

        # JWT validation
        from src.auth.jwt import decode_token

        payload = decode_token(token)
        if payload and payload.get("type") == "access":
            return {
                "user_id": payload.get("sub"),
                "email": payload.get("email"),
                "tenant_id": payload.get("tenant_id"),
                "role": payload.get("role"),
            }

        return {"user_id": None, "tenant_id": None, "role": None}
