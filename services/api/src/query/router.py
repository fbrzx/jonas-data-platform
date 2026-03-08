"""Query Workbench API — ad-hoc SELECT execution with role-scoped layer access."""

import re
import time
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.auth.permissions import Action, Resource, require_permission
from src.db.connection import get_conn
from src.db.tenant_schemas import layer_schema

logger = structlog.get_logger(__name__)

router = APIRouter()

# Roles and the DuckDB schemas they may read
_ROLE_ALLOWED_SCHEMAS: dict[str, set[str]] = {
    "owner": {
        "bronze", "silver", "gold",
        "platform", "catalogue", "transforms", "integrations", "audit",
    },
    "admin":    {"bronze", "silver", "gold", "catalogue", "transforms", "integrations", "audit"},
    "engineer": {"bronze", "silver", "gold", "catalogue", "transforms"},
    "analyst":  {"silver", "gold"},
    "viewer":   {"gold"},
}

_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|TRUNCATE|ALTER|CREATE|REPLACE|GRANT|REVOKE|ATTACH|COPY|EXPORT)\b",
    re.IGNORECASE,
)

_MAX_ROWS = 500


class QueryRequest(BaseModel):
    sql: str = Field(..., min_length=1, max_length=8000)


class QueryResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    duration_ms: float
    truncated: bool


def _user(req: Request) -> dict[str, Any]:
    return req.state.user or {}


def _tenant(req: Request) -> str:
    tid = _user(req).get("tenant_id")
    if not tid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return str(tid)


def _validate_query(sql: str, role: str, tenant_id: str) -> str:
    """Return cleaned SQL or raise HTTPException."""
    stripped = sql.strip().rstrip(";")

    if not re.match(r"^\s*SELECT\b", stripped, re.IGNORECASE):
        raise HTTPException(
            status_code=400,
            detail="Only SELECT statements are permitted in the query workbench.",
        )
    if _FORBIDDEN_KEYWORDS.search(stripped):
        raise HTTPException(
            status_code=400,
            detail="Query contains forbidden keywords (DROP, DELETE, UPDATE, etc.).",
        )

    # Rewrite unqualified layer names to tenant-scoped schemas.
    # e.g. "bronze.orders" → "bronze_acme.orders"
    allowed = _ROLE_ALLOWED_SCHEMAS.get(role, {"gold"})
    for layer in ("bronze", "silver", "gold"):
        schema = layer_schema(layer, tenant_id)
        if layer in allowed:
            stripped = re.sub(
                rf"\b{layer}\b\.", f"{schema}.", stripped, flags=re.IGNORECASE
            )
        else:
            # Block access to layers this role cannot see
            if re.search(rf"\b{layer}\b\.", stripped, re.IGNORECASE):
                raise HTTPException(
                    status_code=403,
                    detail=f"Role '{role}' does not have access to the {layer} layer.",
                )

    return stripped


@router.post("", response_model=QueryResponse)
async def run_query(body: QueryRequest, req: Request) -> QueryResponse:
    user = _user(req)
    require_permission(user, Resource.CATALOGUE, Action.READ)
    tenant_id = _tenant(req)
    role = str(user.get("role", "viewer"))

    sql = _validate_query(body.sql, role, tenant_id)

    conn = get_conn()
    t0 = time.perf_counter()
    try:
        rel = conn.execute(sql)
        col_names = [d[0] for d in rel.description]
        raw_rows = rel.fetchmany(_MAX_ROWS + 1)
    except Exception as exc:
        logger.warning("query_error", tenant_id=tenant_id, role=role, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    duration_ms = (time.perf_counter() - t0) * 1000
    truncated = len(raw_rows) > _MAX_ROWS
    rows = raw_rows[:_MAX_ROWS]

    records = [dict(zip(col_names, row)) for row in rows]
    logger.info(
        "query_executed",
        tenant_id=tenant_id,
        role=role,
        row_count=len(records),
        duration_ms=round(duration_ms, 1),
    )

    return QueryResponse(
        columns=col_names,
        rows=records,
        row_count=len(records),
        duration_ms=round(duration_ms, 1),
        truncated=truncated,
    )


@router.get("/tables")
async def list_tables(req: Request) -> list[dict[str, str]]:
    """Return all tables visible to this role, for autocomplete."""
    user = _user(req)
    require_permission(user, Resource.CATALOGUE, Action.READ)
    tenant_id = _tenant(req)
    role = str(user.get("role", "viewer"))

    allowed_layers = _ROLE_ALLOWED_SCHEMAS.get(role, {"gold"})
    data_layers = ("bronze", "silver", "gold")
    schemas = [layer_schema(layer, tenant_id) for layer in allowed_layers if layer in data_layers]

    conn = get_conn()
    tables: list[dict[str, str]] = []
    for schema in schemas:
        try:
            rows = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = ?",
                [schema],
            ).fetchall()
            for (tname,) in rows:
                layer = schema.split("_")[0]
                tables.append({"schema": schema, "table": tname, "layer": layer})
        except Exception:
            pass

    return tables
