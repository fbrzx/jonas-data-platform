"""Catalogue service — CRUD for data entities and field definitions."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from src.db.connection import get_conn

# Layers each role can access
_ROLE_LAYERS: dict[str, list[str]] = {
    "owner": ["bronze", "silver", "gold"],
    "admin": ["bronze", "silver", "gold"],
    "engineer": ["bronze", "silver", "gold"],
    "analyst": ["silver", "gold"],
    "viewer": ["gold"],
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def list_entities(tenant_id: str) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM catalogue.entity WHERE tenant_id = ?", [tenant_id]
    ).fetchall()
    cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    return [dict(zip(cols, row)) for row in rows]


def get_entity(entity_id: str, tenant_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM catalogue.entity WHERE id = ? AND tenant_id = ?",
        [entity_id, tenant_id],
    ).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    return dict(zip(cols, row))


def create_entity(data: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    conn = get_conn()
    entity_id = str(uuid.uuid4())
    now = _now()
    conn.execute(
        """
        INSERT INTO catalogue.entity
            (id, tenant_id, name, description, layer, tags, meta, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            entity_id,
            tenant_id,
            data["name"],
            data.get("description", ""),
            data.get("layer", "bronze"),
            json.dumps(data.get("tags", [])),
            json.dumps(data.get("meta", data.get("metadata", {}))),
            now,
            now,
        ],
    )
    result = get_entity(entity_id, tenant_id)
    assert result is not None
    return result


def update_entity(
    entity_id: str, data: dict[str, Any], tenant_id: str
) -> dict[str, Any] | None:
    existing = get_entity(entity_id, tenant_id)
    if not existing:
        return None

    # Map API field names → DB column names; skip non-column keys
    _COLUMN_MAP = {"metadata": "meta"}
    _JSON_COLUMNS = {"tags", "meta"}
    _SKIP = {"fields"}  # handled separately via create_fields_bulk

    db_updates: dict[str, Any] = {}
    for k, v in data.items():
        if k in _SKIP or v is None:
            continue
        col = _COLUMN_MAP.get(k, k)
        db_updates[col] = (
            json.dumps(v) if col in _JSON_COLUMNS and not isinstance(v, str) else v
        )

    if not db_updates:
        return existing

    conn = get_conn()
    set_clauses = ", ".join(f"{col} = ?" for col in db_updates)
    values = list(db_updates.values()) + [_now(), entity_id, tenant_id]
    conn.execute(
        f"UPDATE catalogue.entity SET {set_clauses}, updated_at = ? WHERE id = ? AND tenant_id = ?",  # noqa: S608
        values,
    )
    return get_entity(entity_id, tenant_id)


def delete_entity(entity_id: str, tenant_id: str) -> bool:
    existing = get_entity(entity_id, tenant_id)
    if not existing:
        return False
    get_conn().execute(
        "DELETE FROM catalogue.entity WHERE id = ? AND tenant_id = ?",
        [entity_id, tenant_id],
    )
    return True


# ── Field management ─────────────────────────────────────────────────────────


def get_entity_fields(entity_id: str) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM catalogue.entity_field WHERE entity_id = ? ORDER BY ordinal",
        [entity_id],
    ).fetchall()
    cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    return [dict(zip(cols, row)) for row in rows]


def create_fields_bulk(
    entity_id: str, fields: list[dict[str, Any]], created_by: str = "system"
) -> list[dict[str, Any]]:
    """Insert multiple field definitions for an entity."""
    conn = get_conn()
    now = _now()
    created = []
    for field in fields:
        field_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO catalogue.entity_field
                (id, entity_id, name, data_type, nullable, is_pii,
                 description, ordinal, sample_values, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                field_id,
                entity_id,
                field["name"],
                field.get("data_type", "string"),
                bool(field.get("nullable", True)),
                bool(field.get("is_pii", False)),
                field.get("description", ""),
                field.get("ordinal", 0),
                json.dumps(field.get("sample_values", [])),
                created_by,
                now,
            ],
        )
        created.append({**field, "id": field_id, "entity_id": entity_id})
    return created


def get_field(field_id: str, entity_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM catalogue.entity_field WHERE id = ? AND entity_id = ?",
        [field_id, entity_id],
    ).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    return dict(zip(cols, row))


def update_field(
    field_id: str, entity_id: str, data: dict[str, Any]
) -> dict[str, Any] | None:
    existing = get_field(field_id, entity_id)
    if not existing:
        return None

    _ALLOWED = {"data_type", "nullable", "is_pii", "description"}
    db_updates: dict[str, Any] = {
        k: v for k, v in data.items() if k in _ALLOWED and v is not None
    }

    if not db_updates:
        return existing

    conn = get_conn()
    set_clauses = ", ".join(f"{col} = ?" for col in db_updates)
    values = list(db_updates.values()) + [field_id, entity_id]
    conn.execute(
        f"UPDATE catalogue.entity_field SET {set_clauses} WHERE id = ? AND entity_id = ?",  # noqa: S608
        values,
    )
    return get_field(field_id, entity_id)


def delete_field(field_id: str, entity_id: str) -> bool:
    existing = get_field(field_id, entity_id)
    if not existing:
        return False
    get_conn().execute(
        "DELETE FROM catalogue.entity_field WHERE id = ? AND entity_id = ?",
        [field_id, entity_id],
    )
    return True


# ── Catalogue context for NL-to-SQL ─────────────────────────────────────────


def get_accessible_entities(tenant_id: str, role: str) -> list[dict[str, Any]]:
    """Return entities visible to the role, each with their field list."""
    allowed_layers = _ROLE_LAYERS.get(role, ["gold"])
    entities = list_entities(tenant_id)
    accessible = [e for e in entities if e.get("layer") in allowed_layers]
    for entity in accessible:
        entity["fields"] = get_entity_fields(entity["id"])
    return accessible


def preview_entity(
    entity_id: str, tenant_id: str, role: str = "viewer", limit: int = 20
) -> dict[str, Any] | None:
    """Return up to `limit` rows from the entity's DuckDB table with PII masking."""
    entity = get_entity(entity_id, tenant_id)
    if not entity:
        return None

    table_ref = f"{entity['layer']}.{entity['name']}"
    fields = get_entity_fields(entity_id)
    pii_field_names = {f["name"] for f in fields if f.get("is_pii")}
    has_pii_access = role in ("owner", "admin")

    conn = get_conn()
    try:
        rows_raw = conn.execute(
            f"SELECT * FROM {table_ref} LIMIT {limit}"  # noqa: S608
        ).fetchall()
        cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
        rows = [dict(zip(cols, row)) for row in rows_raw]

        if not has_pii_access and pii_field_names:
            from src.agent.pii import mask_rows

            rows = mask_rows(rows, pii_field_names, False)

        return {
            "entity": table_ref,
            "columns": cols,
            "rows": rows,
            "count": len(rows),
            "pii_masked": bool(pii_field_names and not has_pii_access),
            "pii_fields": sorted(pii_field_names),
        }
    except Exception as exc:
        return {
            "entity": table_ref,
            "columns": [],
            "rows": [],
            "count": 0,
            "pii_masked": False,
            "pii_fields": [],
            "error": str(exc),
        }


def build_catalogue_context(tenant_id: str, role: str) -> str:
    """Return a compact text description of the catalogue, integrations and transforms."""
    entities = get_accessible_entities(tenant_id, role)

    lines: list[str] = []

    conn = get_conn()
    entity_map: dict[str, str] = {
        str(e["id"]): f"{e.get('layer','?')}.{e.get('name','?')}" for e in entities
    }

    # ── Entities ─────────────────────────────────────────────────────────────
    if not entities:
        lines.append("## Catalogue\nNo entities registered yet.\n")
    else:
        conn = get_conn()
        lines.append("## Catalogue entities\n")
        for e in entities:
            layer = e.get("layer", "?")
            name = e.get("name", "?")
            table_ref = f"{layer}.{name}"
            desc = e.get("description", "")
            lines.append(
                f"### {table_ref}  (id: {e['id']})" + (f"  — {desc}" if desc else "")
            )

            # Physical columns actually in DuckDB (source of truth for SQL)
            try:
                phys_rows = conn.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
                    [layer, name],
                ).fetchall()
                phys_cols = [r[0] for r in phys_rows]
            except Exception:
                phys_cols = []

            if phys_cols:
                _WEBHOOK_SIG = {
                    "id",
                    "tenant_id",
                    "ingested_at",
                    "source",
                    "payload",
                    "metadata",
                }
                _CSV_SIG = {"_id", "_tenant_id", "_ingested_at"}
                phys_set = set(phys_cols)
                is_webhook_format = _WEBHOOK_SIG.issubset(phys_set)
                is_csv_format = (
                    _CSV_SIG.issubset(phys_set) and "payload" not in phys_set
                )

                if is_webhook_format:
                    lines.append(
                        "  STORAGE: webhook — fields are inside `payload` JSON column. "
                        "Use json_extract_string(payload, '$.field') for strings, "
                        "CAST(json_extract(payload, '$.field') AS type) for typed values. "
                        "NEVER use bare field names as SQL columns."
                    )
                    lines.append(f"  Physical columns: {', '.join(phys_cols)}")
                    # Surface the actual payload keys from a sample row, plus array field hints
                    try:
                        sample_row = conn.execute(
                            f"SELECT payload FROM {layer}.{name} LIMIT 1"  # noqa: S608
                        ).fetchone()
                        if sample_row and sample_row[0]:
                            sample_payload = (
                                json.loads(sample_row[0])
                                if isinstance(sample_row[0], str)
                                else sample_row[0]
                            )
                            if isinstance(sample_payload, dict):
                                keys = list(sample_payload.keys())[:15]
                                lines.append(
                                    f"  Payload keys: {', '.join(keys)}"
                                    f"  — example: json_extract_string(payload, '$.{keys[0]}')"
                                )
                                # Flag JSON array fields with sub-key hints
                                for k, v in sample_payload.items():
                                    if (
                                        isinstance(v, list)
                                        and v
                                        and isinstance(v[0], dict)
                                    ):
                                        sub_keys = list(v[0].keys())[:8]
                                        lines.append(
                                            f"  Array field '{k}': unnest with "
                                            f"CROSS JOIN UNNEST(json_extract(payload, '$.{k}')::JSON[]) AS t(elem)"
                                            f" — sub-keys: {', '.join(sub_keys)}"
                                        )
                            elif (
                                isinstance(sample_payload, list)
                                and sample_payload
                                and isinstance(sample_payload[0], dict)
                            ):
                                keys = list(sample_payload[0].keys())[:15]
                                lines.append(
                                    f"  Payload keys (array/first element): {', '.join(keys)}"
                                )
                    except Exception:
                        pass
                elif is_csv_format:
                    lines.append(
                        f"  STORAGE: csv — use these columns directly (all VARCHAR, CAST as needed): "
                        f"{', '.join(phys_cols)}"
                    )
                else:
                    lines.append(
                        f"  STORAGE: flat — typed structured table (created by transform). "
                        f"Use these columns directly with their native types: {', '.join(phys_cols)}"
                    )
            else:
                lines.append("  (table not yet created in DuckDB — no data ingested)")

            # Catalogue field definitions (logical schema)
            fields: list[dict[str, Any]] = e.get("fields", [])
            if fields and not (phys_cols and "payload" not in phys_cols):
                # Only show catalogue fields as SQL-usable when table has matching columns
                pass
            if fields:
                field_names = ", ".join(f["name"] for f in fields)
                pii_fields = [f["name"] for f in fields if f.get("is_pii")]
                lines.append(f"  Catalogue fields: {field_names}")
                if pii_fields:
                    lines.append(f"  PII fields: {', '.join(pii_fields)}")
            lines.append("")

    # ── Integrations ─────────────────────────────────────────────────────────
    try:
        int_rows = conn.execute(
            "SELECT id, name, connector_type, status, target_entity_id FROM integrations.connector WHERE tenant_id = ?",  # noqa: E501
            [tenant_id],
        ).fetchall()
        int_cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
        integrations = [dict(zip(int_cols, r)) for r in int_rows]
    except Exception:
        integrations = []

    if integrations:
        lines.append("## Connectors (data sources)\n")
        for i in integrations:
            eid = str(i.get("target_entity_id") or "")
            linked = f" → {entity_map.get(eid, eid)}" if eid else " (no entity linked)"
            trigger = (
                f"  trigger: POST /api/v1/connectors/{i['id']}/trigger"
                if i.get("connector_type") == "api_pull"
                else ""
            )
            lines.append(
                f"- {i['name']} (id: {i['id']}, type: {i.get('connector_type')}, "
                f"status: {i.get('status')}){linked}"
            )
            if trigger:
                lines.append(f"  {trigger}")
        lines.append("")

    # ── Transforms ───────────────────────────────────────────────────────────
    try:
        t_rows = conn.execute(
            "SELECT id, name, description, source_layer, target_layer, status, transform_sql FROM transforms.transform WHERE tenant_id = ?",  # noqa: E501
            [tenant_id],
        ).fetchall()
        t_cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
        transforms = [dict(zip(t_cols, r)) for r in t_rows]
    except Exception:
        transforms = []

    if transforms:
        lines.append("## Transforms\n")
        for t in transforms:
            sql_preview = (t.get("transform_sql") or "")[:80].replace("\n", " ")
            desc = t.get("description", "")
            lines.append(
                f"- {t['name']} (id: {t['id']}, {t.get('source_layer')}→{t.get('target_layer')}, "
                f"status: {t.get('status')})" + (f"  — {desc}" if desc else "")
            )
            if sql_preview:
                lines.append(f"  sql: {sql_preview}…")
        lines.append("")

    return "\n".join(lines)
