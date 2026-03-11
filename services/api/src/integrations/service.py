"""Integration service — template selection and config validation."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from src.db.connection import get_conn
from src.security.crypto import decrypt_config, encrypt_config


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _decrypt_row(row: dict[str, Any]) -> dict[str, Any]:
    """Decrypt config and auth_config fields in a connector row if encrypted at rest."""
    if row.get("config"):
        row["config"] = decrypt_config(str(row["config"]))
    if row.get("auth_config"):
        row["auth_config"] = decrypt_config(str(row["auth_config"]))
    return row


def list_integrations(tenant_id: str) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM integrations.connector WHERE tenant_id = ?", [tenant_id]
    ).fetchall()
    cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    return [_decrypt_row(dict(zip(cols, row))) for row in rows]


def get_integration(integration_id: str, tenant_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM integrations.connector WHERE id = ? AND tenant_id = ?",
        [integration_id, tenant_id],
    ).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    return _decrypt_row(dict(zip(cols, row)))


def create_integration(data: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    conn = get_conn()
    integration_id = str(uuid.uuid4())
    now = _now()
    raw_config = encrypt_config(json.dumps(data.get("config", {})))
    raw_auth_config = encrypt_config(json.dumps(data.get("auth_config", {})))

    # Ensure entity link: resolve or auto-create a bronze entity
    entity_id = data.get("entity_id")
    if not entity_id:
        from src.catalogue.service import create_entity

        name = data["name"]
        # Look up existing bronze entity by name
        existing = conn.execute(
            "SELECT id FROM catalogue.entity WHERE tenant_id = ? AND name = ? AND layer = 'bronze'",
            [tenant_id, name],
        ).fetchone()
        if existing:
            entity_id = str(existing[0])
        else:
            entity = create_entity(
                {"name": name, "layer": "bronze", "description": data.get("description", ""),
                 "collection": data.get("collection")},
                tenant_id,
            )
            entity_id = str(entity["id"])

    conn.execute(
        """
        INSERT INTO integrations.connector
            (id, tenant_id, name, description, connector_type, config, auth_config,
             status, tags, target_entity_id, collection, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
        """,
        [
            integration_id,
            tenant_id,
            data["name"],
            data.get("description", ""),
            data["connector_type"],
            raw_config,
            raw_auth_config,
            json.dumps(data.get("tags", [])),
            entity_id,
            data.get("collection"),
            now,
            now,
        ],
    )
    result = get_integration(integration_id, tenant_id)
    assert result is not None
    return result


def update_integration(
    integration_id: str, data: dict[str, Any], tenant_id: str
) -> dict[str, Any] | None:
    existing = get_integration(integration_id, tenant_id)
    if not existing:
        return None

    _ENCRYPTED_JSON_COLUMNS = {"config", "auth_config"}
    _PLAIN_JSON_COLUMNS = {"tags"}
    _ALLOWED_COLS = {
        "name",
        "description",
        "status",
        "config",
        "auth_config",
        "tags",
        "target_entity_id",
        "cron_schedule",
        "collection",
    }
    # connector_type is immutable — always excluded
    data.pop("connector_type", None)
    # entity_id in the API maps to target_entity_id in the DB
    if "entity_id" in data:
        data["target_entity_id"] = data.pop("entity_id")

    db_updates: dict[str, Any] = {}
    for k, v in data.items():
        if v is None or k not in _ALLOWED_COLS:
            continue
        if k in _ENCRYPTED_JSON_COLUMNS and not isinstance(v, str):
            db_updates[k] = encrypt_config(json.dumps(v))
        elif k in _PLAIN_JSON_COLUMNS and not isinstance(v, str):
            db_updates[k] = json.dumps(v)
        else:
            db_updates[k] = v

    if not db_updates:
        return existing

    conn = get_conn()
    set_clauses = ", ".join(f"{col} = ?" for col in db_updates)
    values = list(db_updates.values()) + [_now(), integration_id, tenant_id]
    conn.execute(
        f"UPDATE integrations.connector SET {set_clauses}, updated_at = ? WHERE id = ? AND tenant_id = ?",  # noqa: S608 E501
        values,
    )
    return get_integration(integration_id, tenant_id)


def delete_integration(integration_id: str, tenant_id: str) -> None:
    get_conn().execute(
        "DELETE FROM integrations.connector WHERE id = ? AND tenant_id = ?",
        [integration_id, tenant_id],
    )


def list_runs(
    integration_id: str, tenant_id: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Return recent runs for an integration, newest first."""
    conn = get_conn()
    # Verify the integration belongs to this tenant before returning runs
    integration = get_integration(integration_id, tenant_id)
    if not integration:
        return []
    rows = conn.execute(
        """
        SELECT * FROM integrations.connector_run
        WHERE integration_id = ?
        ORDER BY started_at DESC
        LIMIT ?
        """,
        [integration_id, limit],
    ).fetchall()
    cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    return [dict(zip(cols, row)) for row in rows]
