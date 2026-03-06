"""JWT creation/validation and password hashing (stdlib PBKDF2)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from src.config import settings

_ALGORITHM = "HS256"
_ACCESS_TTL = timedelta(hours=1)
_REFRESH_TTL = timedelta(days=7)
_PBKDF2_ITERS = 260_000


# ── Password hashing ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERS)
    return f"pbkdf2:sha256:{_PBKDF2_ITERS}:{salt}:{base64.urlsafe_b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, _, iters, salt, expected = stored.split(":")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters))
        computed = base64.urlsafe_b64encode(dk).decode()
        return hmac.compare_digest(computed, expected)
    except Exception:
        return False


# ── JWT ───────────────────────────────────────────────────────────────────────

def _make_token(data: dict[str, Any], ttl: timedelta) -> str:
    payload = {**data, "exp": datetime.now(UTC) + ttl}
    return jwt.encode(payload, settings.api_secret_key, algorithm=_ALGORITHM)


def create_access_token(user_id: str, email: str, tenant_id: str, role: str) -> str:
    return _make_token(
        {"sub": user_id, "email": email, "tenant_id": tenant_id, "role": role, "type": "access"},
        _ACCESS_TTL,
    )


def create_refresh_token(user_id: str, tenant_id: str) -> str:
    return _make_token(
        {"sub": user_id, "tenant_id": tenant_id, "type": "refresh"},
        _REFRESH_TTL,
    )


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.api_secret_key, algorithms=[_ALGORITHM])
    except JWTError:
        return None
