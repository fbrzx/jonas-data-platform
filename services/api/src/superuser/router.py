"""Platform super user API — tenant management and super user administration.

All endpoints require is_superuser=True. Super users are platform-level admins
who can manage all tenants and access any tenant's data as an admin.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.audit.log import write_audit
from src.auth.jwt import hash_password
from src.auth.permissions import require_superuser
from src.db.connection import get_conn

router = APIRouter()


def _superuser(request: Request) -> dict[str, Any]:
    user = getattr(request.state, "user", None) or {}
    require_superuser(user)
    return user


# ── Tenant management ──────────────────────────────────────────────────────────


@router.get("/tenants")
async def list_tenants(request: Request) -> list[dict[str, Any]]:
    """List all tenants with member counts."""
    _superuser(request)
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT
            t.id,
            t.slug,
            t.name,
            t.storage_prefix,
            t.created_at,
            COUNT(m.id) FILTER (WHERE m.revoked_at IS NULL) AS active_members,
            COUNT(m.id) AS total_members
        FROM platform.tenant t
        LEFT JOIN platform.tenant_membership m ON m.tenant_id = t.id
        GROUP BY t.id, t.slug, t.name, t.storage_prefix, t.created_at
        ORDER BY t.created_at ASC
        """
    ).fetchall()
    cols = [
        "id",
        "slug",
        "name",
        "storage_prefix",
        "created_at",
        "active_members",
        "total_members",
    ]
    return [dict(zip(cols, r)) for r in rows]


class TenantCreate(BaseModel):
    slug: str
    name: str


@router.post("/tenants", status_code=201)
async def create_tenant(request: Request, body: TenantCreate) -> dict[str, Any]:
    """Create a new tenant and provision its data lake schemas."""
    su = _superuser(request)
    conn = get_conn()

    # Validate slug (alphanumeric + hyphens)
    import re

    if not re.match(r"^[a-z0-9][a-z0-9\-]{1,62}[a-z0-9]$", body.slug):
        raise HTTPException(
            status_code=422,
            detail="Slug must be 3–64 lowercase alphanumeric characters or hyphens",
        )

    # Check uniqueness
    existing = conn.execute(
        "SELECT id FROM platform.tenant WHERE slug = ?", [body.slug]
    ).fetchone()
    if existing:
        raise HTTPException(
            status_code=409, detail="A tenant with this slug already exists"
        )

    now = datetime.now(UTC).isoformat()
    tenant_id = conn.execute("SELECT gen_random_uuid()").fetchone()[0]  # type: ignore[index]
    storage_prefix = f"tenants/{body.slug}"

    conn.execute(
        "INSERT INTO platform.tenant (id, slug, name, storage_prefix, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [tenant_id, body.slug, body.name, storage_prefix, now],
    )

    # Provision bronze/silver/gold schemas for this tenant
    try:
        from src.db.tenant_schemas import provision_tenant_schemas

        provision_tenant_schemas(tenant_id)
    except Exception as exc:
        import structlog

        structlog.get_logger(__name__).warning(
            "schema_provisioning_failed", tenant_id=tenant_id, error=repr(exc)
        )

    write_audit(
        tenant_id=tenant_id,
        user_id=su.get("user_id"),
        action="create_tenant",
        resource_type="tenant",
        resource_id=tenant_id,
        detail={"slug": body.slug, "name": body.name},
    )
    return {
        "id": tenant_id,
        "slug": body.slug,
        "name": body.name,
        "storage_prefix": storage_prefix,
        "created_at": now,
        "active_members": 0,
        "total_members": 0,
    }


class TenantUpdate(BaseModel):
    name: str | None = None


@router.patch("/tenants/{tenant_id}")
async def update_tenant(
    request: Request, tenant_id: str, body: TenantUpdate
) -> dict[str, Any]:
    """Update a tenant's display name."""
    su = _superuser(request)
    conn = get_conn()

    row = conn.execute(
        "SELECT id, slug, name, storage_prefix, created_at FROM platform.tenant WHERE id = ?",
        [tenant_id],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")

    updates: dict[str, Any] = body.model_dump(exclude_none=True)
    if not updates:
        cols = ["id", "slug", "name", "storage_prefix", "created_at"]
        return dict(zip(cols, row))

    if "name" in updates:
        conn.execute(
            "UPDATE platform.tenant SET name = ? WHERE id = ?",
            [updates["name"], tenant_id],
        )

    write_audit(
        tenant_id=tenant_id,
        user_id=su.get("user_id"),
        action="update_tenant",
        resource_type="tenant",
        resource_id=tenant_id,
        detail=updates,
    )

    updated = conn.execute(
        "SELECT id, slug, name, storage_prefix, created_at FROM platform.tenant WHERE id = ?",
        [tenant_id],
    ).fetchone()
    cols = ["id", "slug", "name", "storage_prefix", "created_at"]
    return dict(zip(cols, updated))


@router.delete("/tenants/{tenant_id}", status_code=204)
async def delete_tenant(request: Request, tenant_id: str) -> None:
    """Delete a tenant and all its memberships permanently."""
    su = _superuser(request)
    conn = get_conn()

    row = conn.execute(
        "SELECT id FROM platform.tenant WHERE id = ?", [tenant_id]
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")

    write_audit(
        tenant_id=tenant_id,
        user_id=su.get("user_id"),
        action="delete_tenant",
        resource_type="tenant",
        resource_id=tenant_id,
    )

    # Delete memberships first, then the tenant row
    conn.execute(
        "DELETE FROM platform.tenant_membership WHERE tenant_id = ?", [tenant_id]
    )
    conn.execute("DELETE FROM platform.tenant WHERE id = ?", [tenant_id])


# ── Tenant member inspection ───────────────────────────────────────────────────


@router.get("/tenants/{tenant_id}/users")
async def list_tenant_users(request: Request, tenant_id: str) -> list[dict[str, Any]]:
    """List all members of any tenant (super user view)."""
    _superuser(request)
    conn = get_conn()

    row = conn.execute(
        "SELECT id FROM platform.tenant WHERE id = ?", [tenant_id]
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")

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


# ── Super user management ──────────────────────────────────────────────────────


@router.get("/users")
async def list_superusers(request: Request) -> list[dict[str, Any]]:
    """List all platform super users."""
    _superuser(request)
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT id, email, display_name, created_at
        FROM platform.user_account
        WHERE is_superuser = TRUE
        ORDER BY created_at ASC
        """
    ).fetchall()
    cols = ["id", "email", "display_name", "created_at"]
    return [dict(zip(cols, r)) for r in rows]


class SuperUserCreate(BaseModel):
    email: str
    display_name: str
    password: str


@router.post("/users", status_code=201)
async def create_superuser(request: Request, body: SuperUserCreate) -> dict[str, Any]:
    """Create a new platform super user account."""
    su = _superuser(request)
    conn = get_conn()

    existing = conn.execute(
        "SELECT id FROM platform.user_account WHERE email = ?", [body.email]
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    pw_hash = hash_password(body.password)
    now = datetime.now(UTC).isoformat()
    user_id = conn.execute("SELECT gen_random_uuid()").fetchone()[0]  # type: ignore[index]

    conn.execute(
        "INSERT INTO platform.user_account "
        "(id, email, display_name, password_hash, is_superuser, created_at) "
        "VALUES (?, ?, ?, ?, TRUE, ?)",
        [user_id, body.email, body.display_name, pw_hash, now],
    )

    write_audit(
        tenant_id="platform",
        user_id=su.get("user_id"),
        action="create_superuser",
        resource_type="user",
        resource_id=user_id,
        detail={"email": body.email},
    )
    return {
        "id": user_id,
        "email": body.email,
        "display_name": body.display_name,
        "created_at": now,
    }


@router.delete("/users/{user_id}", status_code=204)
async def revoke_superuser(request: Request, user_id: str) -> None:
    """Remove super user privileges from a user account."""
    su = _superuser(request)
    requester_id = su.get("user_id")

    if user_id == requester_id:
        raise HTTPException(
            status_code=400, detail="Cannot remove your own super user privileges"
        )

    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM platform.user_account WHERE id = ? AND is_superuser = TRUE",
        [user_id],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Super user not found")

    conn.execute(
        "UPDATE platform.user_account SET is_superuser = FALSE WHERE id = ?",
        [user_id],
    )

    write_audit(
        tenant_id="platform",
        user_id=requester_id,
        action="revoke_superuser",
        resource_type="user",
        resource_id=user_id,
    )
