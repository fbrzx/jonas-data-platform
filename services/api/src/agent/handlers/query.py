"""Query tool handler: run_sql."""

import json
import re
from typing import Any

from src.db.connection import get_conn

_TOOLS = {"run_sql"}

_ROLE_ALLOWED_LAYERS: dict[str, set[str]] = {
    "owner": {"bronze", "silver", "gold"},
    "admin": {"bronze", "silver", "gold"},
    "engineer": {"bronze", "silver", "gold"},
    "analyst": {"silver", "gold"},
    "viewer": {"gold"},
}
_LAYER_PATTERN = re.compile(r"\b(bronze|silver|gold)\.\w+", re.IGNORECASE)
_MAX_SQL_ROWS = 20
_MAX_TOOL_RESULT_CHARS = 4000


def _check_sql_scope(sql: str, role: str) -> str | None:
    allowed = _ROLE_ALLOWED_LAYERS.get(role, {"gold"})
    for match in _LAYER_PATTERN.finditer(sql):
        layer = match.group(1).lower()
        if layer not in allowed:
            return (
                f"Access denied: your role ({role}) cannot query the {layer} layer. "
                f"You have access to: {', '.join(sorted(allowed))}."
            )
    return None


def handle(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    tenant_id: str,
    role: str,
    created_by: str,
) -> str | None:
    if tool_name not in _TOOLS:
        return None

    conn = get_conn()
    sql = tool_input.get("sql", "").strip()
    limit = min(int(tool_input.get("limit", _MAX_SQL_ROWS)), 1000)

    if not sql.upper().startswith("SELECT"):
        return json.dumps({"error": "Only SELECT statements are permitted."})

    scope_error = _check_sql_scope(sql, role)
    if scope_error:
        return json.dumps({"error": scope_error})

    from src.db.tenant_schemas import inject_tenant_schemas as _inject_sql

    try:
        rows_raw = conn.execute(
            f"{_inject_sql(sql, tenant_id)} LIMIT {limit}"  # noqa: S608
        ).fetchall()
        cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
        rows = [dict(zip(cols, row)) for row in rows_raw]

        if role not in ("owner", "admin"):
            from src.agent.inference import _is_pii  # type: ignore[attr-defined]
            from src.agent.pii import mask_rows as _mask

            pii_cols = {c for c in cols if _is_pii(c)}
            rows = _mask(rows, pii_cols, False)

        result_payload: dict[str, Any] = {"rows": rows, "count": len(rows)}
        if len(json.dumps(result_payload, default=str)) > _MAX_TOOL_RESULT_CHARS:
            while (
                rows
                and len(json.dumps(result_payload, default=str))
                > _MAX_TOOL_RESULT_CHARS
            ):
                rows = rows[:-1]
            result_payload = {
                "rows": rows,
                "count": len(rows),
                "truncated": True,
                "note": f"Result truncated to {len(rows)} rows to fit context window.",
            }
        return json.dumps(result_payload, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})
