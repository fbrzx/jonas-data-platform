"""Transform service — draft, approve, execute lifecycle."""

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from src.db.connection import get_conn


def _now() -> str:
    return datetime.now(UTC).isoformat()


def list_transforms(tenant_id: str) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM transforms.transform WHERE tenant_id = ?", [tenant_id]
    ).fetchall()
    cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    return [dict(zip(cols, row)) for row in rows]


def get_transform(transform_id: str, tenant_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM transforms.transform WHERE id = ? AND tenant_id = ?",
        [transform_id, tenant_id],
    ).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    return dict(zip(cols, row))


def create_transform(
    data: dict[str, Any], tenant_id: str, created_by: str
) -> dict[str, Any]:
    conn = get_conn()
    transform_id = str(uuid.uuid4())
    now = _now()
    conn.execute(
        """
        INSERT INTO transforms.transform
            (id, tenant_id, name, description, source_layer, target_layer,
             transform_sql, status, created_by, tags, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)
        """,
        [
            transform_id,
            tenant_id,
            data["name"],
            data.get("description", ""),
            data.get("source_layer", "bronze"),
            data.get("target_layer", "silver"),
            data.get("sql", data.get("transform_sql", "")),
            created_by,
            json.dumps(data.get("tags", [])),
            now,
            now,
        ],
    )
    result = get_transform(transform_id, tenant_id)
    assert result is not None
    return result


def approve_transform(
    transform_id: str, action: str, approved_by: str, tenant_id: str
) -> dict[str, Any] | None:
    existing = get_transform(transform_id, tenant_id)
    if not existing:
        return None
    status = "approved" if action == "approve" else "rejected"
    conn = get_conn()
    conn.execute(
        "UPDATE transforms.transform"
        " SET status = ?, approved_by = ?, updated_at = ? WHERE id = ? AND tenant_id = ?",
        [status, approved_by, _now(), transform_id, tenant_id],
    )
    return get_transform(transform_id, tenant_id)


def execute_transform(transform_id: str, tenant_id: str) -> dict[str, Any]:
    transform = get_transform(transform_id, tenant_id)
    if not transform:
        raise ValueError(f"Transform {transform_id} not found")
    if transform.get("status") != "approved":
        raise ValueError("Only approved transforms can be executed")

    conn = get_conn()
    start = time.monotonic()
    errors: list[str] = []
    rows_affected = 0
    target_table = (
        f"{transform['target_layer']}.{transform['name'].lower().replace(' ', '_')}"
    )

    run_id = str(uuid.uuid4())
    started_at = _now()

    # Record run start
    conn.execute(
        """
        INSERT INTO transforms.transform_run
            (id, transform_id, status, started_at)
        VALUES (?, ?, 'running', ?)
        """,
        [run_id, transform_id, started_at],
    )

    try:
        conn.execute(transform["transform_sql"])
        # CTAS / DDL statements don't return rows — query the target table for count
        try:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {target_table}"  # noqa: S608
            ).fetchone()
            rows_affected = int(row[0]) if row else 0
        except Exception:
            rows_affected = 0
    except Exception as exc:
        errors.append(str(exc))

    duration_ms = (time.monotonic() - start) * 1000
    completed_at = _now()
    run_status = "failed" if errors else "success"

    # Update run record
    conn.execute(
        """
        UPDATE transforms.transform_run
        SET status = ?, completed_at = ?, rows_produced = ?, error_detail = ?
        WHERE id = ?
        """,
        [
            run_status,
            completed_at,
            rows_affected,
            json.dumps({"errors": errors}) if errors else None,
            run_id,
        ],
    )

    # Stamp last_run_at on the transform itself
    conn.execute(
        "UPDATE transforms.transform SET last_run_at = ? WHERE id = ?",
        [completed_at, transform_id],
    )

    return {
        "transform_id": transform_id,
        "rows_affected": rows_affected,
        "duration_ms": round(duration_ms, 2),
        "target_table": target_table,
        "executed_at": completed_at,
        "errors": errors,
    }


def delete_transform(transform_id: str, tenant_id: str) -> None:
    get_conn().execute(
        "DELETE FROM transforms.transform WHERE id = ? AND tenant_id = ?",
        [transform_id, tenant_id],
    )
