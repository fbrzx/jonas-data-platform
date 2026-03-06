"""Audit API — unified jobs view and audit log."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from src.auth.permissions import Action, Resource, require_permission
from src.db.connection import get_conn

router = APIRouter()


def _user(request: Request) -> dict[str, Any]:
    return request.state.user or {}


def _tenant(request: Request) -> str:
    from fastapi import HTTPException

    user = _user(request)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return str(tid)


@router.get("/jobs")
async def list_jobs(
    request: Request,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """Unified view of connector_run + transform_run, newest first."""
    require_permission(_user(request), Resource.INTEGRATION, Action.READ)
    tenant_id = _tenant(request)
    conn = get_conn()
    offset = (page - 1) * page_size

    rows = conn.execute(
        """
        SELECT
            cr.id,
            'connector' AS job_type,
            c.name AS job_name,
            c.connector_type AS sub_type,
            cr.status,
            cr.started_at,
            cr.completed_at,
            cr.records_in,
            cr.records_out,
            cr.records_rejected,
            cr.error_detail
        FROM integrations.connector_run cr
        JOIN integrations.connector c ON c.id = cr.integration_id
        WHERE c.tenant_id = ?

        UNION ALL

        SELECT
            tr.id,
            'transform' AS job_type,
            t.name AS job_name,
            t.target_layer AS sub_type,
            tr.status,
            tr.started_at,
            tr.completed_at,
            COALESCE(tr.rows_produced, 0) AS records_in,
            COALESCE(tr.rows_produced, 0) AS records_out,
            0 AS records_rejected,
            NULL AS error_detail
        FROM transforms.transform_run tr
        JOIN transforms.transform t ON t.id = tr.transform_id
        WHERE t.tenant_id = ?

        ORDER BY started_at DESC
        LIMIT ? OFFSET ?
        """,
        [tenant_id, tenant_id, page_size, offset],
    ).fetchall()

    count_row = conn.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT cr.id FROM integrations.connector_run cr
            JOIN integrations.connector c ON c.id = cr.integration_id
            WHERE c.tenant_id = ?
            UNION ALL
            SELECT tr.id FROM transforms.transform_run tr
            JOIN transforms.transform t ON t.id = tr.transform_id
            WHERE t.tenant_id = ?
        )
        """,
        [tenant_id, tenant_id],
    ).fetchone()

    cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    jobs = [dict(zip(cols, r)) for r in rows]
    # Re-fetch description after count query
    total = count_row[0] if count_row else 0

    return {"jobs": jobs, "total": total, "page": page, "page_size": page_size}


@router.get("/logs")
async def list_logs(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    action: str | None = None,
    entity_type: str | None = None,
) -> dict[str, Any]:
    """Query audit.audit_log with optional filters."""
    require_permission(_user(request), Resource.INTEGRATION, Action.READ)
    tenant_id = _tenant(request)
    conn = get_conn()
    offset = (page - 1) * page_size

    filters: list[str] = ["tenant_id = ?"]
    params: list[Any] = [tenant_id]
    if action:
        filters.append("action = ?")
        params.append(action)
    if entity_type:
        filters.append("resource_type = ?")
        params.append(entity_type)

    where = " AND ".join(filters)
    rows = conn.execute(
        f"SELECT * FROM audit.audit_log WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",  # noqa: S608
        params + [page_size, offset],
    ).fetchall()
    cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    logs = [dict(zip(cols, r)) for r in rows]

    count_row = conn.execute(
        f"SELECT COUNT(*) FROM audit.audit_log WHERE {where}",  # noqa: S608
        params,
    ).fetchone()
    total = count_row[0] if count_row else 0

    return {"logs": logs, "total": total, "page": page, "page_size": page_size}
