"""Transform tool handlers: list_transforms, draft_transform, update_transform."""

import json
import re
from typing import Any

from src.db.connection import get_conn

_TOOLS = {"list_transforms", "draft_transform", "update_transform"}


def _sql_error_hint(err: str) -> str:
    e = err.lower()
    if "json_array_elements" in e or "json_each" in e:
        return (
            " Hint: json_array_elements and json_each are Postgres functions — "
            "not supported in DuckDB. Use: "
            "CROSS JOIN UNNEST(json_extract(payload, '$.array_field')::JSON[]) AS t(elem)"
        )
    if "lateral" in e and "join" in e:
        return (
            " Hint: CROSS JOIN LATERAL is not supported in DuckDB. "
            "Use: CROSS JOIN UNNEST(json_extract(payload, '$.array_field')::JSON[]) AS t(elem)"
        )
    if "unnest" in e and ("json" in e or "cast" in e or "type" in e):
        return (
            " Hint: UNNEST requires an array type. Cast the JSON array first: "
            "UNNEST(json_extract(payload, '$.array_field')::JSON[]) AS t(elem). "
            "The ::JSON[] cast is required."
        )
    col_match = re.search(r'does not have a column named "([^"]+)"', err, re.IGNORECASE)
    if col_match:
        col = col_match.group(1)
        return (
            f' Hint: "{col}" is not a physical column. '
            "For webhook/api_pull tables the field lives inside the `payload` JSON column — "
            f"use json_extract_string(payload, '$.{col}') for strings. "
            "Call describe_entity to see physical_columns and payload_keys."
        )
    return ""


def _validate_sql_dry_run(sql: str, conn: Any) -> str | None:
    """Execute each SELECT block with LIMIT 1 to catch runtime errors before saving."""
    select_blocks: list[str] = []
    for m in re.finditer(r"(?i)\bAS\s+(SELECT\b.+?)(?=;|$)", sql, re.DOTALL):
        select_blocks.append(m.group(1).strip().rstrip(";"))
    for m in re.finditer(
        r"(?i)\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+\S+\s+(SELECT\b.+?)(?=;|$)",
        sql,
        re.DOTALL,
    ):
        select_blocks.append(m.group(1).strip().rstrip(";"))
    if not select_blocks and re.match(r"(?i)\s*SELECT\b", sql.strip()):
        select_blocks.append(sql.strip().rstrip(";"))
    for sel in select_blocks:
        try:
            conn.execute(f"SELECT * FROM ({sel}) AS _dry_run_q LIMIT 1")  # noqa: S608
        except Exception as exc:
            return str(exc)
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

    # ── list_transforms ──────────────────────────────────────────────────────
    if tool_name == "list_transforms":
        from src.transforms.service import list_transforms

        transforms = list_transforms(tenant_id)
        return json.dumps(
            [
                {
                    "id": t["id"],
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "source_layer": t.get("source_layer"),
                    "target_layer": t.get("target_layer"),
                    "status": t.get("status"),
                    "trigger_mode": t.get("trigger_mode", "manual"),
                    "sql_preview": (t.get("transform_sql") or "")[:120],
                }
                for t in transforms
            ]
        )

    # ── draft_transform ──────────────────────────────────────────────────────
    if tool_name == "draft_transform":
        from src.transforms.service import create_transform

        if not tool_input.get("name"):
            return json.dumps({"error": "draft_transform requires 'name'."})

        sql = (tool_input.get("sql") or tool_input.get("transform_sql") or "").strip()
        if sql:
            from src.db.tenant_schemas import inject_tenant_schemas as _inject_dry

            err = _validate_sql_dry_run(_inject_dry(sql, tenant_id), conn)
            if err is not None:
                return json.dumps(
                    {
                        "error": f"SQL validation failed before saving: {err}.{_sql_error_hint(err)}",  # noqa: E501
                        "sql": sql,
                    }
                )

        try:
            result = create_transform(tool_input, tenant_id, created_by=created_by)
        except Exception as exc:
            err_msg = str(exc)
            if "Duplicate key" in err_msg or "unique constraint" in err_msg.lower():
                name = tool_input.get("name", "")
                return json.dumps(
                    {
                        "error": f"Transform '{name}' already exists. Use update_transform to modify it."
                    }
                )
            return json.dumps({"error": err_msg})
        return json.dumps(result, default=str)

    # ── update_transform ─────────────────────────────────────────────────────
    if tool_name == "update_transform":
        from src.transforms.service import update_transform

        transform_id = tool_input.pop("transform_id", None)
        if not transform_id:
            return json.dumps({"error": "transform_id is required."})

        new_sql = (
            tool_input.get("transform_sql") or tool_input.get("sql") or ""
        ).strip()
        if new_sql:
            from src.db.tenant_schemas import inject_tenant_schemas as _inject_upd

            err = _validate_sql_dry_run(_inject_upd(new_sql, tenant_id), conn)
            if err is not None:
                return json.dumps(
                    {
                        "error": f"SQL validation failed — transform not updated: {err}.{_sql_error_hint(err)}",  # noqa: E501
                        "sql": new_sql,
                    }
                )

        result = update_transform(transform_id, tool_input, tenant_id)
        if not result:
            return json.dumps({"error": f"Transform '{transform_id}' not found."})
        return json.dumps(result, default=str)

    return None
