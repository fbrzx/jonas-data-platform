"""Auth endpoints — login / refresh / me."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.audit.log import write_audit
from src.auth.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from src.db.connection import get_conn

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


def _lookup_user(email: str) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute(
        """
        SELECT u.id, u.email, u.display_name, u.password_hash,
               m.tenant_id, m.role
        FROM platform.user_account u
        JOIN platform.tenant_membership m ON m.user_id = u.id
        WHERE u.email = ?
        LIMIT 1
        """,
        [email],
    ).fetchone()
    if not row:
        return None
    cols = ["id", "email", "display_name", "password_hash", "tenant_id", "role"]
    return dict(zip(cols, row))


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> dict[str, str]:
    user = _lookup_user(body.email)
    if not user or not user.get("password_hash"):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    write_audit(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        action="login",
        resource_type="user",
        resource_id=user["id"],
    )
    return {
        "access_token": create_access_token(
            user["id"], user["email"], user["tenant_id"], user["role"]
        ),
        "refresh_token": create_refresh_token(user["id"], user["tenant_id"]),
        "token_type": "bearer",
    }


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest) -> dict[str, str]:
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user_id: str = payload["sub"]
    tenant_id: str = payload["tenant_id"]
    conn = get_conn()
    row = conn.execute(
        """
        SELECT u.email, m.role
        FROM platform.user_account u
        JOIN platform.tenant_membership m ON m.user_id = u.id AND m.tenant_id = ?
        WHERE u.id = ?
        """,
        [tenant_id, user_id],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="User not found")
    email, role = row
    return {
        "access_token": create_access_token(user_id, email, tenant_id, role),
        "refresh_token": create_refresh_token(user_id, tenant_id),
        "token_type": "bearer",
    }


class AcceptInviteRequest(BaseModel):
    token: str
    display_name: str
    password: str


@router.post("/accept-invite", response_model=TokenResponse)
async def accept_invite(body: AcceptInviteRequest) -> dict[str, str]:
    from datetime import UTC, datetime

    from src.auth.jwt import hash_password

    conn = get_conn()
    now = datetime.now(UTC)

    row = conn.execute(
        "SELECT id, tenant_id, email, role, expires_at, used_at FROM platform.invite WHERE token = ?",  # noqa: E501
        [body.token],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Invalid or expired invite link")

    invite_id, tenant_id, email, role, expires_at_str, used_at = row
    if used_at:
        raise HTTPException(status_code=409, detail="This invite has already been used")

    # Check expiry
    try:
        expires_at = datetime.fromisoformat(str(expires_at_str).replace("Z", "+00:00"))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if now.replace(tzinfo=UTC) > expires_at:
            raise HTTPException(status_code=410, detail="This invite link has expired")
    except HTTPException:
        raise
    except Exception:
        pass  # If parsing fails, proceed (lenient)

    # Check if email already registered
    existing = conn.execute(
        "SELECT id FROM platform.user_account WHERE email = ?", [email]
    ).fetchone()
    if existing:
        raise HTTPException(
            status_code=409, detail="An account with this email already exists"
        )

    pw_hash = hash_password(body.password)
    now_str = now.isoformat()
    user_id = conn.execute("SELECT gen_random_uuid()").fetchone()[0]  # type: ignore[index]

    conn.execute(
        "INSERT INTO platform.user_account (id, email, display_name, password_hash, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [user_id, email, body.display_name, pw_hash, now_str],
    )

    membership_id = conn.execute("SELECT gen_random_uuid()").fetchone()[0]  # type: ignore[index]
    conn.execute(
        "INSERT INTO platform.tenant_membership (id, tenant_id, user_id, role, granted_at, granted_by) "  # noqa: E501
        "VALUES (?, ?, ?, ?, ?, ?)",
        [membership_id, tenant_id, user_id, role, now_str, "invite"],
    )

    conn.execute(
        "UPDATE platform.invite SET used_at = ? WHERE id = ?",
        [now_str, invite_id],
    )

    write_audit(
        tenant_id=tenant_id,
        user_id=user_id,
        action="accept_invite",
        resource_type="user",
        resource_id=user_id,
        detail={"email": email, "role": role},
    )

    return {
        "access_token": create_access_token(user_id, email, tenant_id, role),
        "refresh_token": create_refresh_token(user_id, tenant_id),
        "token_type": "bearer",
    }


@router.get("/me")
async def me(request: Request) -> dict[str, Any]:
    user = getattr(request.state, "user", None) or {}
    if not user.get("user_id"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {
        "user_id": user["user_id"],
        "email": user.get("email"),
        "tenant_id": user["tenant_id"],
        "role": user["role"],
    }
