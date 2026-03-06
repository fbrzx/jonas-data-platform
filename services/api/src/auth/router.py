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
