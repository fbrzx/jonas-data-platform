"""Shared SlowAPI rate-limiter instance.

Key function: authenticated user_id when available, remote IP otherwise.
Import this module everywhere a rate limit decorator is needed to ensure
all limits share the same in-memory counter store.
"""

from fastapi import Request
from slowapi import Limiter  # type: ignore[attr-defined]
from slowapi.util import get_remote_address


def _get_user_id(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    return str(user.get("user_id") or get_remote_address(request))


limiter = Limiter(key_func=_get_user_id)
