"""Tenant administration — config and user management (admin only)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.audit.log import write_audit
from src.auth.jwt import hash_password
from src.auth.permissions import Action, Resource, require_permission
from src.db.connection import get_conn

router = APIRouter()

_CONFIG_DEFAULTS: dict[str, Any] = {
    "llm_provider": "ollama",
    "llm_model": "llama3.2",
    "pii_masking_enabled": True,
    "data_retention_days": 90,
    "max_connector_runs_per_day": 100,
}

_VALID_ROLES = {"admin", "analyst", "viewer"}


def _user(request: Request) -> dict[str, Any]:
    return request.state.user or {}


def _tenant(request: Request) -> str:
    user = _user(request)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return str(tid)


# ── Tenant Config ──────────────────────────────────────────────────────────────


@router.get("/config")
async def get_config(request: Request) -> dict[str, Any]:
    require_permission(_user(request), Resource.USER, Action.ADMIN)
    tenant_id = _tenant(request)
    conn = get_conn()
    rows = conn.execute(
        "SELECT key, value FROM platform.tenant_config WHERE tenant_id = ?",
        [tenant_id],
    ).fetchall()
    stored = {r[0]: json.loads(r[1]) if isinstance(r[1], str) else r[1] for r in rows}
    return {**_CONFIG_DEFAULTS, **stored}


class ConfigPatch(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    pii_masking_enabled: bool | None = None
    data_retention_days: int | None = None
    max_connector_runs_per_day: int | None = None


@router.patch("/config")
async def update_config(request: Request, body: ConfigPatch) -> dict[str, Any]:
    require_permission(_user(request), Resource.USER, Action.ADMIN)
    tenant_id = _tenant(request)
    user_id = _user(request).get("user_id")
    conn = get_conn()
    now = datetime.now(UTC).isoformat()

    updates = body.model_dump(exclude_none=True)
    for key, val in updates.items():
        conn.execute(
            """
            INSERT INTO platform.tenant_config (tenant_id, key, value, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (tenant_id, key) DO UPDATE SET
                value = excluded.value,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            [tenant_id, key, json.dumps(val), user_id, now],
        )

    return await get_config(request)


# ── Tenant Users ───────────────────────────────────────────────────────────────


@router.get("/users")
async def list_users(request: Request) -> list[dict[str, Any]]:
    require_permission(_user(request), Resource.USER, Action.ADMIN)
    tenant_id = _tenant(request)
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT
            u.id,
            u.email,
            u.display_name,
            m.role,
            m.granted_at,
            m.revoked_at
        FROM platform.tenant_membership m
        JOIN platform.user_account u ON u.id = m.user_id
        WHERE m.tenant_id = ?
        ORDER BY m.granted_at ASC
        """,
        [tenant_id],
    ).fetchall()
    cols = ["id", "email", "display_name", "role", "granted_at", "revoked_at"]
    return [dict(zip(cols, r)) for r in rows]


class UserCreate(BaseModel):
    email: str
    display_name: str
    password: str
    role: str = "analyst"


@router.post("/users", status_code=201)
async def create_user(request: Request, body: UserCreate) -> dict[str, Any]:
    require_permission(_user(request), Resource.USER, Action.ADMIN)
    tenant_id = _tenant(request)
    admin_id = _user(request).get("user_id")

    if body.role not in _VALID_ROLES:
        raise HTTPException(
            status_code=422, detail=f"role must be one of {sorted(_VALID_ROLES)}"
        )

    conn = get_conn()

    # Check email is not already in use
    existing = conn.execute(
        "SELECT id FROM platform.user_account WHERE email = ?",
        [body.email],
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    pw_hash = hash_password(body.password)
    now = datetime.now(UTC).isoformat()

    user_id = conn.execute("SELECT gen_random_uuid()").fetchone()[0]  # type: ignore[index]
    conn.execute(
        "INSERT INTO platform.user_account (id, email, display_name, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
        [user_id, body.email, body.display_name, pw_hash, now],
    )

    membership_id = conn.execute("SELECT gen_random_uuid()").fetchone()[0]  # type: ignore[index]
    conn.execute(
        "INSERT INTO platform.tenant_membership (id, tenant_id, user_id, role, granted_at, granted_by) VALUES (?, ?, ?, ?, ?, ?)",
        [membership_id, tenant_id, user_id, body.role, now, admin_id],
    )

    write_audit(
        tenant_id=tenant_id,
        user_id=admin_id,
        action="create_user",
        resource_type="user",
        resource_id=user_id,
        detail={"email": body.email, "role": body.role},
    )
    return {
        "id": user_id,
        "email": body.email,
        "display_name": body.display_name,
        "role": body.role,
        "granted_at": now,
        "revoked_at": None,
    }


class RolePatch(BaseModel):
    role: str


@router.patch("/users/{user_id}/role")
async def change_role(
    request: Request, user_id: str, body: RolePatch
) -> dict[str, Any]:
    require_permission(_user(request), Resource.USER, Action.ADMIN)
    tenant_id = _tenant(request)

    if body.role not in _VALID_ROLES:
        raise HTTPException(
            status_code=422, detail=f"role must be one of {sorted(_VALID_ROLES)}"
        )

    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM platform.tenant_membership WHERE tenant_id = ? AND user_id = ? AND revoked_at IS NULL",
        [tenant_id, user_id],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found in this tenant")

    conn.execute(
        "UPDATE platform.tenant_membership SET role = ? WHERE tenant_id = ? AND user_id = ?",
        [body.role, tenant_id, user_id],
    )
    write_audit(
        tenant_id=tenant_id,
        user_id=_user(request).get("user_id"),
        action="change_role",
        resource_type="user",
        resource_id=user_id,
        detail={"new_role": body.role},
    )
    return {"user_id": user_id, "role": body.role}


@router.delete("/users/{user_id}", status_code=204)
async def revoke_user(request: Request, user_id: str) -> None:
    require_permission(_user(request), Resource.USER, Action.ADMIN)
    tenant_id = _tenant(request)
    requester_id = _user(request).get("user_id")

    if user_id == requester_id:
        raise HTTPException(status_code=400, detail="Cannot revoke your own access")

    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM platform.tenant_membership WHERE tenant_id = ? AND user_id = ? AND revoked_at IS NULL",
        [tenant_id, user_id],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found in this tenant")

    now = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE platform.tenant_membership SET revoked_at = ? WHERE tenant_id = ? AND user_id = ?",
        [now, tenant_id, user_id],
    )
    write_audit(
        tenant_id=tenant_id,
        user_id=requester_id,
        action="revoke_user",
        resource_type="user",
        resource_id=user_id,
    )
