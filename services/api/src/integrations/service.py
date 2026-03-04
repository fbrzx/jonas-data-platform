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
             status, tags, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
        """,
        [
            integration_id,
            tenant_id,
            data["name"],
            data.get("description", ""),
            data["connector_type"],
            json.dumps(data.get("config", {})),
            json.dumps(data.get("tags", [])),
            now,
            now,
        ],
    )
    result = get_integration(integration_id, tenant_id)
    assert result is not None
    return result


def delete_integration(integration_id: str, tenant_id: str) -> None:
    get_conn().execute(
        "DELETE FROM integrations.integration WHERE id = ? AND tenant_id = ?",
        [integration_id, tenant_id],
    )
