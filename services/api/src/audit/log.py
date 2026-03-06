"""Shared audit-log writer — fire-and-forget, never raises."""

from __future__ import annotations

import json
from typing import Any

from src.db.connection import get_conn


def write_audit(
    *,
    tenant_id: str,
    user_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    detail: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Insert one row into audit.audit_log. Swallows all exceptions."""
    try:
        get_conn().execute(
            """
            INSERT INTO audit.audit_log
                (tenant_id, user_id, action, resource_type, resource_id, detail, ip_address)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                tenant_id,
                user_id,
                action,
                resource_type,
                resource_id,
                json.dumps(detail or {}),
                ip_address,
            ],
        )
    except Exception:
        pass  # audit failures must never break the main request
