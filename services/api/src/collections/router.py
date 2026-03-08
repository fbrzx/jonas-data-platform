"""Collections API — list and manage collection tags across the tenant."""

from typing import Any

from fastapi import APIRouter, Request

from src.auth.permissions import Action, Resource, require_permission
from src.db.connection import get_conn

router = APIRouter()


def _tenant(request: Request) -> str:
    user = request.state.user or {}
    tid = user.get("tenant_id")
    if not tid:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Not authenticated")
    return str(tid)


@router.get("")
async def list_collections(request: Request) -> list[dict[str, Any]]:
    """Return all distinct collection names for the tenant with item counts."""
    user = request.state.user or {}
    require_permission(user, Resource.CATALOGUE, Action.READ)
    tenant_id = _tenant(request)
    conn = get_conn()

    # Gather distinct collection names across all three resource types,
    # then count per type in a single pass.
    rows = conn.execute(
        """
        WITH all_collections AS (
            SELECT collection, 'entity'    AS kind FROM catalogue.entity
             WHERE tenant_id = ? AND collection IS NOT NULL
            UNION ALL
            SELECT collection, 'transform' AS kind FROM transforms.transform
             WHERE tenant_id = ? AND collection IS NOT NULL
            UNION ALL
            SELECT collection, 'connector' AS kind FROM integrations.connector
             WHERE tenant_id = ? AND collection IS NOT NULL
        )
        SELECT
            collection,
            COUNT(*) FILTER (WHERE kind = 'entity')    AS entity_count,
            COUNT(*) FILTER (WHERE kind = 'transform') AS transform_count,
            COUNT(*) FILTER (WHERE kind = 'connector') AS connector_count,
            COUNT(*)                                    AS total
        FROM all_collections
        GROUP BY collection
        ORDER BY collection
        """,
        [tenant_id, tenant_id, tenant_id],
    ).fetchall()

    return [
        {
            "name": r[0],
            "entity_count": r[1],
            "transform_count": r[2],
            "connector_count": r[3],
            "total": r[4],
        }
        for r in rows
    ]
