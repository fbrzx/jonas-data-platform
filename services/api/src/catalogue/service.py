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


# ── Catalogue context for NL-to-SQL ─────────────────────────────────────────


def get_accessible_entities(tenant_id: str, role: str) -> list[dict[str, Any]]:
    """Return entities visible to the role, each with their field list."""
    allowed_layers = _ROLE_LAYERS.get(role, ["gold"])
    entities = list_entities(tenant_id)
    accessible = [e for e in entities if e.get("layer") in allowed_layers]
    for entity in accessible:
        entity["fields"] = get_entity_fields(entity["id"])
    return accessible


def build_catalogue_context(tenant_id: str, role: str) -> str:
    """Return a compact text description of the catalogue for the system prompt."""
    entities = get_accessible_entities(tenant_id, role)
    if not entities:
        return "No entities in catalogue yet."

    lines: list[str] = ["## Available tables\n"]
    for e in entities:
        layer = e.get("layer", "?")
        name = e.get("name", "?")
        table_ref = f"{layer}.{name}"
        desc = e.get("description", "")
        lines.append(f"### {table_ref}" + (f"  — {desc}" if desc else ""))
        fields: list[dict[str, Any]] = e.get("fields", [])
        if fields:
            for f in fields:
                pii_tag = " [PII]" if f.get("is_pii") else ""
                nullable_tag = " nullable" if f.get("nullable") else ""
                lines.append(
                    f"  - {f['name']}: {f.get('data_type','string')}{nullable_tag}{pii_tag}"
                )
        else:
            lines.append("  (no fields registered yet)")
        lines.append("")

    return "\n".join(lines)
