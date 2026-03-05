"""OpenAPI authentication helpers.

These dependencies exist to expose Bearer auth in Swagger/OpenAPI.
Runtime auth/tenant enforcement remains in AuthMiddleware + permission checks.
"""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Paste one of the demo tokens: admin-token, analyst-token, viewer-token",
)


def docs_bearer_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str | None:
    """Declare Bearer auth in OpenAPI without changing runtime auth behavior."""
    return credentials.credentials if credentials else None
