"""Transform tool handlers: list_transforms, draft_transform, update_transform."""

import json
import re
from typing import Any

from src.db.connection import get_conn

_TOOLS = {"list_transforms", "draft_transform", "update_transform", "execute_transform"}


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
                    "collection": t.get("collection"),
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

        # Prerequisite: confirm source table actually has data before creating the transform.
        source_layer = tool_input.get("source_layer", "bronze")
        sql_check = (tool_input.get("sql") or tool_input.get("transform_sql") or "").strip()
        if sql_check:
            # Extract the first FROM clause table name to verify data exists
            import re as _re

            from src.db.tenant_schemas import inject_tenant_schemas as _inject_prereq

            from_match = _re.search(
                r"\bFROM\s+([a-z_][a-z0-9_.]*)", sql_check, _re.IGNORECASE
            )
            if from_match:
                src_table = _inject_prereq(from_match.group(1), tenant_id)
                try:
                    row = conn.execute(
                        f"SELECT COUNT(*) FROM {src_table}"  # noqa: S608
                    ).fetchone()
                    count = int(row[0]) if row else 0
                    if count == 0:
                        return json.dumps(
                            {
                                "prerequisite_not_met": True,
                                "error": (
                                    f"Source table '{from_match.group(1)}' is empty — "
                                    "no data has been ingested yet. "
                                    "Trigger or ingest data first, then draft the transform."
                                ),
                                "suggested_next_steps": [
                                    "Call list_connectors to find a connector for this table.",
                                    "Use trigger_connector or ingest_webhook to load data.",
                                    "Then call draft_transform again.",
                                ],
                            }
                        )
                except Exception:
                    # Table doesn't exist yet — source data not available
                    return json.dumps(
                        {
                            "prerequisite_not_met": True,
                            "error": (
                                f"Source table '{from_match.group(1)}' does not exist. "
                                f"Ensure data is ingested into {source_layer} before "
                                "drafting a transform that reads from it."
                            ),
                            "suggested_next_steps": [
                                "Call list_connectors to find or create a connector.",
                                "Ingest or trigger data, then retry draft_transform.",
                            ],
                        }
                    )

        sql = sql_check
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
                        "error": (
                            f"Transform '{name}' already exists. "
                            "Use update_transform to modify it."
                        )
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

    # ── execute_transform ─────────────────────────────────────────────────────
    if tool_name == "execute_transform":
        from src.auth.permissions import Action, Resource, can
        from src.transforms.service import execute_transform, get_transform

        if not can({"role": role}, Resource.TRANSFORM, Action.APPROVE):
            return json.dumps(
                {
                    "error": (
                        f"Access denied: role '{role}' cannot execute transforms. "
                        "Requires engineer, admin, or owner role."
                    )
                }
            )

        transform_id = tool_input.get("transform_id", "")
        if not transform_id:
            return json.dumps({"error": "transform_id is required."})

        transform = get_transform(transform_id, tenant_id)
        if not transform:
            return json.dumps({"error": f"Transform '{transform_id}' not found."})

        status = transform.get("status")
        if status != "approved":
            return json.dumps(
                {
                    "prerequisite_not_met": True,
                    "error": (
                        f"Transform '{transform.get('name')}' has status '{status}' "
                        "and cannot be executed. Only approved transforms can run."
                    ),
                    "suggested_next_steps": (
                        ["Ask an engineer, admin, or owner to approve it first."]
                        if status == "draft"
                        else [
                            "The transform was rejected. Update the SQL and resubmit for approval."
                        ]
                    ),
                }
            )

        try:
            result = execute_transform(transform_id, tenant_id)
        except Exception as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps(result, default=str)

    return None
