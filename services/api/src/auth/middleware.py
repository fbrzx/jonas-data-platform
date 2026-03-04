"""Token → user + tenant resolution middleware."""

from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

# Public paths that don't require authentication
PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        token = self._extract_token(request)
        if token:
            user_context = await self._resolve_token(token)
            request.state.user = user_context
        else:
            request.state.user = None

        return await call_next(request)

    @staticmethod
    def _extract_token(request: Request) -> str | None:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[len("Bearer ") :]
        return request.headers.get("X-API-Token")

    @staticmethod
    async def _resolve_token(token: str) -> dict[str, Any]:
        """Resolve a bearer token to user + tenant context.

        In the prototype this is a simple lookup. Replace with JWT validation
        or a DB call in production.
        """
        # Demo tokens — map to hardcoded user/tenant for prototype
        demo_tokens: dict[str, dict[str, Any]] = {
            "admin-token": {
                "user_id": "user-admin",
                "email": "admin@acme.io",
                "tenant_id": "tenant-acme",
                "role": "admin",
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
        return demo_tokens.get(
            token, {"user_id": None, "tenant_id": None, "role": None}
        )
