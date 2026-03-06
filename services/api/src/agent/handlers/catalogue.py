"""Catalogue tool handlers: list_entities, describe_entity, infer_schema, register_entity, preview_entity."""

import json
from typing import Any

from src.agent.pii import mask_rows
from src.db.connection import get_conn

_TOOLS = {
    "list_entities",
    "describe_entity",
    "infer_schema",
    "register_entity",
    "preview_entity",
}

# Result truncation limits (shared with query.py)
_MAX_PREVIEW_ROWS = 10
_MAX_TOOL_RESULT_CHARS = 4000


def _pii_fields_for_entity(entity_id: str) -> set[str]:
    from src.catalogue.service import get_entity_fields

    return {f["name"] for f in get_entity_fields(entity_id) if f.get("is_pii")}


def _has_pii_access(role: str) -> bool:
    return role in ("owner", "admin")


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

    # ── list_entities ────────────────────────────────────────────────────────
    if tool_name == "list_entities":
        from src.catalogue.service import get_accessible_entities

        entities = get_accessible_entities(tenant_id, role)
        layer = tool_input.get("layer")
        if layer:
            entities = [e for e in entities if e.get("layer") == layer]
        summary = [
            {
                "id": e["id"],
                "name": e["name"],
                "layer": e.get("layer"),
                "description": e.get("description", ""),
                "field_count": len(e.get("fields", [])),
            }
            for e in entities
        ]
        return json.dumps(summary)

    # ── describe_entity ──────────────────────────────────────────────────────
    if tool_name == "describe_entity":
        from src.catalogue.service import get_entity, get_entity_fields
        from src.db.tenant_schemas import layer_schema as _layer_schema

        entity_id_arg = tool_input.get("entity_id")
        if not entity_id_arg:
            return json.dumps({"error": "describe_entity requires 'entity_id'."})
        entity = get_entity(entity_id_arg, tenant_id)
        if not entity:
            return json.dumps({"error": "Entity not found"})
        entity["fields"] = get_entity_fields(entity["id"])

        layer = entity.get("layer", "bronze")
        name = entity.get("name", "")
        scoped_schema = _layer_schema(layer, tenant_id)
        try:
            phys_rows = conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
                [scoped_schema, name],
            ).fetchall()
            phys_cols = [r[0] for r in phys_rows]
            _WEBHOOK_SIGNATURE = {
                "id",
                "tenant_id",
                "ingested_at",
                "source",
                "payload",
                "metadata",
            }
            _CSV_SIGNATURE = {"_id", "_tenant_id", "_ingested_at"}
            phys_set = set(phys_cols)
            is_webhook = _WEBHOOK_SIGNATURE.issubset(phys_set)
            is_csv = _CSV_SIGNATURE.issubset(phys_set) and "payload" not in phys_set

            entity["physical_columns"] = phys_cols
            if is_webhook:
                entity["storage_format"] = "webhook"
                entity["sql_hint"] = (
                    "WEBHOOK FORMAT: logical fields are inside the `payload` JSON column. "
                    "Use json_extract_string(payload, '$.field') for strings, "
                    "CAST(json_extract(payload, '$.field') AS DOUBLE/TIMESTAMP/etc) for typed values. "
                    "Never reference catalogue field names as direct SQL columns — they do not exist."
                )
                try:
                    row = conn.execute(
                        f"SELECT payload FROM {scoped_schema}.{name} LIMIT 1"  # noqa: S608
                    ).fetchone()
                    if row and row[0]:
                        sample = (
                            json.loads(row[0]) if isinstance(row[0], str) else row[0]
                        )
                        if isinstance(sample, dict):
                            entity["payload_keys"] = list(sample.keys())[:20]
                            array_fields: dict[str, list[str]] = {}
                            for k, v in sample.items():
                                if isinstance(v, list) and v and isinstance(v[0], dict):
                                    array_fields[k] = list(v[0].keys())[:10]
                            if array_fields:
                                entity["payload_array_fields"] = array_fields
                                entity["unnest_hint"] = (
                                    "DuckDB JSON array unnesting — required syntax: "
                                    "CROSS JOIN UNNEST(json_extract(payload, '$.array_field')::JSON[]) AS t(elem). "
                                    "Access sub-fields with json_extract_string(t.elem, '$.sub_key'). "
                                    "NOT supported: CROSS JOIN LATERAL, json_array_elements, json_each."
                                )
                        elif (
                            isinstance(sample, list)
                            and sample
                            and isinstance(sample[0], dict)
                        ):
                            entity["payload_keys"] = list(sample[0].keys())[:20]
                except Exception:
                    pass
            elif is_csv:
                entity["storage_format"] = "csv"
                entity["sql_hint"] = (
                    "CSV FORMAT: use physical_columns directly (strip the leading _ from _id/_tenant_id/_ingested_at). "
                    "All user data columns are VARCHAR — CAST as needed."
                )
            else:
                entity["storage_format"] = "flat"
                entity["sql_hint"] = (
                    "FLAT FORMAT: typed structured table (created by a transform). "
                    "Use physical_columns directly — no JSON extraction needed."
                )
        except Exception:
            pass

        result_str = json.dumps(entity, default=str)
        if len(result_str) > _MAX_TOOL_RESULT_CHARS:
            entity["fields"] = [
                {"name": f["name"], "data_type": f.get("data_type")}
                for f in entity.get("fields", [])
            ]
            result_str = json.dumps(entity, default=str)
        return result_str

    # ── infer_schema ─────────────────────────────────────────────────────────
    if tool_name == "infer_schema":
        from src.agent.inference import infer_from_csv, infer_from_json

        sample = tool_input.get("sample")
        fmt = tool_input.get("format", "json")
        try:
            if fmt == "csv" and isinstance(sample, list):
                headers = list(sample[0].keys()) if sample else []
                fields = infer_from_csv(headers, sample)
            else:
                fields = infer_from_json(sample)  # type: ignore[arg-type]
            return json.dumps(
                {
                    "field_count": len(fields),
                    "fields": fields,
                    "pii_fields": [f["name"] for f in fields if f.get("is_pii")],
                }
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # ── register_entity ──────────────────────────────────────────────────────
    if tool_name == "register_entity":
        from src.catalogue.service import create_entity, create_fields_bulk

        if not tool_input.get("name"):
            return json.dumps({"error": "register_entity requires 'name'."})
        layer = tool_input.get("layer", "bronze")
        if layer not in ("bronze", "silver", "gold"):
            layer = "bronze"
        entity_data = {
            "name": tool_input["name"],
            "layer": layer,
            "description": tool_input.get("description", ""),
            "tags": [tool_input["namespace"]] if tool_input.get("namespace") else [],
        }
        entity = create_entity(entity_data, tenant_id)
        fields = create_fields_bulk(
            entity["id"], tool_input.get("fields", []), created_by
        )
        entity["fields"] = fields
        return json.dumps(entity, default=str)

    # ── preview_entity ───────────────────────────────────────────────────────
    if tool_name == "preview_entity":
        from src.catalogue.service import get_entity
        from src.db.tenant_schemas import layer_schema as _layer_schema2

        _ROLE_ALLOWED_LAYERS: dict[str, set[str]] = {
            "owner": {"bronze", "silver", "gold"},
            "admin": {"bronze", "silver", "gold"},
            "engineer": {"bronze", "silver", "gold"},
            "analyst": {"silver", "gold"},
            "viewer": {"gold"},
        }

        entity_id = tool_input.get("entity_id")
        if not entity_id:
            return json.dumps({"error": "preview_entity requires 'entity_id'."})
        limit = min(int(tool_input.get("limit", _MAX_PREVIEW_ROWS)), 100)
        entity = get_entity(entity_id, tenant_id)
        if not entity:
            return json.dumps({"error": "Entity not found"})

        allowed_layers = _ROLE_ALLOWED_LAYERS.get(role, {"gold"})
        if entity.get("layer") not in allowed_layers:
            return json.dumps(
                {
                    "error": f"Access denied: role ({role}) cannot access the {entity['layer']} layer."
                }
            )

        table_ref = f"{_layer_schema2(entity['layer'], tenant_id)}.{entity['name']}"
        try:
            rows_raw = conn.execute(
                f"SELECT * FROM {table_ref} LIMIT {limit}"
            ).fetchall()  # noqa: S608
            cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
            rows = [dict(zip(cols, row)) for row in rows_raw]
            rows = mask_rows(
                rows, _pii_fields_for_entity(entity_id), _has_pii_access(role)
            )

            payload: dict[str, Any] = {
                "entity": table_ref,
                "rows": rows,
                "count": len(rows),
            }
            if len(json.dumps(payload, default=str)) > _MAX_TOOL_RESULT_CHARS:
                while (
                    rows
                    and len(json.dumps(payload, default=str)) > _MAX_TOOL_RESULT_CHARS
                ):
                    rows = rows[:-1]
                payload = {
                    "entity": table_ref,
                    "rows": rows,
                    "count": len(rows),
                    "truncated": True,
                    "note": f"Result truncated to {len(rows)} rows to fit context window.",
                }
            return json.dumps(payload, default=str)
        except Exception as exc:
            return json.dumps({"error": str(exc), "entity": table_ref})

    return None  # unreachable but satisfies type checker
