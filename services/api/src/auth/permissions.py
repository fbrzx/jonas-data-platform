"""Permission resolution service.

Resolves effective permissions from role defaults + per-user grant overrides.
"""

from enum import StrEnum
from typing import Any


class Action(StrEnum):
    READ = "read"
    WRITE = "write"
    APPROVE = "approve"
    ADMIN = "admin"


class Resource(StrEnum):
    CATALOGUE = "catalogue"
    INTEGRATION = "integration"
    TRANSFORM = "transform"
    AGENT = "agent"
    USER = "user"


# Role-based defaults: role → {resource → set of allowed actions}
ROLE_DEFAULTS: dict[str, dict[str, set[str]]] = {
    "admin": {
        Resource.CATALOGUE: {Action.READ, Action.WRITE, Action.APPROVE, Action.ADMIN},
        Resource.INTEGRATION: {Action.READ, Action.WRITE, Action.APPROVE, Action.ADMIN},
        Resource.TRANSFORM: {Action.READ, Action.WRITE, Action.APPROVE, Action.ADMIN},
        Resource.AGENT: {Action.READ, Action.WRITE},
        Resource.USER: {Action.READ, Action.WRITE, Action.ADMIN},
    },
    "analyst": {
        Resource.CATALOGUE: {Action.READ, Action.WRITE},
        Resource.INTEGRATION: {Action.READ, Action.WRITE},
        Resource.TRANSFORM: {Action.READ, Action.WRITE},
        Resource.AGENT: {Action.READ, Action.WRITE},
        Resource.USER: {Action.READ},
    },
    "viewer": {
        Resource.CATALOGUE: {Action.READ},
        Resource.INTEGRATION: {Action.READ},
        Resource.TRANSFORM: {Action.READ},
        Resource.AGENT: {Action.READ},
        Resource.USER: set(),
    },
}


def can(user_context: dict[str, Any], resource: str, action: str) -> bool:
    """Return True if the user is permitted to perform `action` on `resource`."""
    role: str = user_context.get("role") or "viewer"
    role_permissions = ROLE_DEFAULTS.get(role, {})
    allowed_actions = role_permissions.get(resource, set())
    return action in allowed_actions


def require_permission(
    user_context: dict[str, Any], resource: str, action: str
) -> None:
    """Raise PermissionError if the user lacks the required permission."""
    if not can(user_context, resource, action):
        raise PermissionError(
            f"User '{user_context.get('email')}' lacks '{action}' on '{resource}'"
        )
