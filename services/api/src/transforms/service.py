"""Transform service — draft, approve, execute lifecycle."""

import json
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from src.db.connection import get_conn


def _now() -> str:
    return datetime.now(UTC).isoformat()


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_ALLOWED_STMT = re.compile(
    r"^\s*(SELECT|INSERT\s+OR\s+REPLACE|INSERT\s+OR\s+IGNORE|CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+)?TABLE)",
    re.IGNORECASE | re.DOTALL,
)


def _split_sql_statements(sql: str) -> list[str]:
    """Split semicolon-delimited SQL into individual non-empty statements.

    Strips leading comment lines from each chunk so that a statement beginning
    with a block of comments is not mistakenly treated as empty.
    """
    stmts = []
    for chunk in sql.split(";"):
        lines = [ln for ln in chunk.splitlines() if not ln.strip().startswith("--")]
        cleaned = "\n".join(lines).strip()
        if cleaned:
            stmts.append(cleaned)
    return stmts


def _validate_transform_sql(sql: str) -> None:
    """Raise ValueError if any statement uses forbidden operations."""
    for stmt in _split_sql_statements(sql):
        if not _ALLOWED_STMT.match(stmt):
            raise ValueError(
                "Transform SQL must only contain SELECT, INSERT OR REPLACE, "
                "INSERT OR IGNORE, or CREATE TABLE statements. "
                "DROP, DELETE, UPDATE, and TRUNCATE are not permitted."
            )


def _extract_select_blocks(sql: str) -> list[str]:
    """Return all SELECT sub-queries from a (possibly multi-statement) SQL block.

    Used for dry-run validation — we only want to execute the SELECT parts,
    not CREATE TABLE or INSERT INTO (which reference tables that may not exist yet).
    """
    blocks: list[str] = []
    for stmt in _split_sql_statements(sql):
        # CTAS: CREATE TABLE ... AS SELECT ...
        m = re.search(r"(?i)\bAS\s+(SELECT\b.+)", stmt, re.DOTALL)
        if m:
            blocks.append(m.group(1).strip())
            continue
        # INSERT [OR ...] INTO table SELECT ...
        m = re.search(
            r"(?i)\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+\S+\s+(SELECT\b.+)", stmt, re.DOTALL
        )
        if m:
            blocks.append(m.group(1).strip())
            continue
        # Bare SELECT
        if re.match(r"(?i)\s*SELECT\b", stmt):
            blocks.append(stmt)
    return blocks


def _validate_identifier(value: str, field_name: str) -> str:
    candidate = value.strip().lower()
    if not _SAFE_IDENTIFIER.fullmatch(candidate):
        raise ValueError(f"Invalid {field_name}: {value!r}")
    return candidate


def _safe_table_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value.strip().lower())
    cleaned = cleaned.strip("_")
    if not cleaned:
        return "transform_output"
    if cleaned[0].isdigit():
        return f"t_{cleaned}"
    return cleaned


def _ensure_layer_schema(conn: Any, layer: str) -> str:
    safe_layer = _validate_identifier(layer, "layer")
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {safe_layer}")  # noqa: S608
    return safe_layer


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
    sql = data.get("sql", data.get("transform_sql", "")).strip()
    if sql:
        _validate_transform_sql(sql)
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


def update_transform(
    transform_id: str, data: dict[str, Any], tenant_id: str
) -> dict[str, Any] | None:
    existing = get_transform(transform_id, tenant_id)
    if not existing:
        return None

    is_draft = existing.get("status") == "draft"
    _JSON_COLUMNS = {"tags"}
    _COLUMN_MAP = {"sql": "transform_sql"}

    db_updates: dict[str, Any] = {}
    for k, v in data.items():
        if v is None:
            continue
        col = _COLUMN_MAP.get(k, k)
        db_updates[col] = (
            json.dumps(v) if col in _JSON_COLUMNS and not isinstance(v, str) else v
        )

    # If SQL is being changed on a non-draft transform, reset status to draft
    # so the updated SQL goes through the approval flow again.
    if "transform_sql" in db_updates and not is_draft:
        db_updates["status"] = "draft"

    if not db_updates:
        return existing

    conn = get_conn()
    set_clauses = ", ".join(f"{col} = ?" for col in db_updates)
    values = list(db_updates.values()) + [_now(), transform_id, tenant_id]
    try:
        conn.execute(
            f"UPDATE transforms.transform SET {set_clauses}, updated_at = ? WHERE id = ? AND tenant_id = ?",  # noqa: S608 E501
            values,
        )
    except Exception as exc:
        if "unique" in str(exc).lower() or "constraint" in str(exc).lower():
            raise ValueError(f"Name conflict: {exc}") from exc
        raise
    return get_transform(transform_id, tenant_id)


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
    _ensure_layer_schema(conn, str(transform["source_layer"]))
    target_layer = _ensure_layer_schema(conn, str(transform["target_layer"]))
    start = time.monotonic()
    errors: list[str] = []
    rows_affected = 0

    # Infer target table from SQL (CREATE TABLE or INSERT INTO) rather than transform name,
    # since the SQL is the source of truth for what gets created.
    sql_for_target = str(transform.get("transform_sql", ""))
    target_table_match = re.search(
        r"(?i)\b(?:CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?|INSERT\s+(?:OR\s+\w+\s+)?INTO\s+)([a-z_][a-z0-9_.]*)",
        sql_for_target,
    )
    if target_table_match:
        target_table = target_table_match.group(1)
    else:
        target_name = _safe_table_name(str(transform["name"]))
        target_table = f"{target_layer}.{target_name}"

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

    # Pre-validate: check statement types + dry-run the SELECT parts with LIMIT 1.
    # We only EXPLAIN/run the SELECT parts so we don't hit "table not found" errors
    # when the CREATE TABLE hasn't run yet (two-statement upsert pattern).
    sql = str(transform["transform_sql"])
    try:
        _validate_transform_sql(sql)
    except ValueError as exc:
        errors.append(str(exc))

    if not errors:
        for sel in _extract_select_blocks(sql):
            try:
                conn.execute(
                    f"SELECT * FROM ({sel.rstrip(';')}) AS _pre_validate_q LIMIT 1"  # noqa: S608
                )
            except Exception as exc:
                err = str(exc)
                hint = ""
                col_match = re.search(
                    r'does not have a column named "([^"]+)"', err, re.IGNORECASE
                )
                if col_match:
                    col = col_match.group(1)
                    hint = (
                        f' Hint: "{col}" is not a physical column. '
                        "For webhook/api_pull tables the field lives inside the "
                        f"`payload` JSON column — use json_extract_string(payload, '$.{col}'). "
                        "Call update_transform with the corrected SQL before re-approving."
                    )
                errors.append(f"SQL validation error: {err}.{hint}")
                break  # stop at first SELECT error

    if not errors:
        # Execute each statement in sequence — DuckDB conn.execute() only runs
        # one statement at a time, so multi-statement transforms (CREATE + INSERT)
        # must be split and executed individually.
        stmts = _split_sql_statements(sql)
        try:
            for stmt in stmts:
                conn.execute(stmt)
            # Query the target table for final row count
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
