"""Integration service — template selection and config validation."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from src.db.connection import get_conn


def _now() -> str:
    return datetime.now(UTC).isoformat()


def list_integrations(tenant_id: str) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM integrations.integration WHERE tenant_id = ?", [tenant_id]
    ).fetchall()
    cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    return [dict(zip(cols, row)) for row in rows]


def get_integration(integration_id: str, tenant_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM integrations.integration WHERE id = ? AND tenant_id = ?",
        [integration_id, tenant_id],
    ).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    return dict(zip(cols, row))


def create_integration(data: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    conn = get_conn()
    integration_id = str(uuid.uuid4())
    now = _now()
    conn.execute(
        """
        INSERT INTO integrations.integration
            (id, tenant_id, name, description, connector_type, config,
             status, tags, target_entity_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
        """,
        [
            integration_id,
            tenant_id,
            data["name"],
            data.get("description", ""),
            data["connector_type"],
            json.dumps(data.get("config", {})),
            json.dumps(data.get("tags", [])),
            data.get("entity_id"),
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

    _JSON_COLUMNS = {"config", "tags"}
    # connector_type is immutable — always excluded
    data.pop("connector_type", None)

    db_updates: dict[str, Any] = {}
    for k, v in data.items():
        if v is None:
            continue
        db_updates[k] = json.dumps(v) if k in _JSON_COLUMNS and not isinstance(v, str) else v

    if not db_updates:
        return existing

    conn = get_conn()
    set_clauses = ", ".join(f"{col} = ?" for col in db_updates)
    values = list(db_updates.values()) + [_now(), integration_id, tenant_id]
    conn.execute(
        f"UPDATE integrations.integration SET {set_clauses}, updated_at = ? WHERE id = ? AND tenant_id = ?",  # noqa: S608 E501
        values,
    )
    return get_integration(integration_id, tenant_id)


def delete_integration(integration_id: str, tenant_id: str) -> None:
    get_conn().execute(
        "DELETE FROM integrations.integration WHERE id = ? AND tenant_id = ?",
        [integration_id, tenant_id],
    )


def list_runs(integration_id: str, tenant_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent runs for an integration, newest first."""
    conn = get_conn()
    # Verify the integration belongs to this tenant before returning runs
    integration = get_integration(integration_id, tenant_id)
    if not integration:
        return []
    rows = conn.execute(
        """
        SELECT * FROM integrations.integration_run
        WHERE integration_id = ?
        ORDER BY started_at DESC
        LIMIT ?
        """,
        [integration_id, limit],
    ).fetchall()
    cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    return [dict(zip(cols, row)) for row in rows]
