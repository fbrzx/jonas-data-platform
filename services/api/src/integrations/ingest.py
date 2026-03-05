"""Inbound ingestion: webhook + batch upload → bronze layer."""

import csv
import io
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from src.db.connection import get_conn


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _bronze_table(source: str) -> str:
    """Derive a safe bronze table name from the source identifier."""
    safe = "".join(c if c.isalnum() else "_" for c in source.lower())
    return f"bronze.{safe}"


def _safe_col(name: str) -> str:
    """Sanitize a CSV column name for use as a SQL identifier."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name)


def _ensure_bronze_schema(conn: Any) -> None:
    conn.execute("CREATE SCHEMA IF NOT EXISTS bronze")


def land_webhook(
    source: str,
    data: dict[str, Any] | list[Any],
    metadata: dict[str, Any],
    tenant_id: str,
) -> dict[str, Any]:
    """Land a webhook payload into the bronze layer."""
    conn = get_conn()
    table = _bronze_table(source)
    _ensure_bronze_schema(conn)

    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id VARCHAR PRIMARY KEY,
            tenant_id VARCHAR NOT NULL,
            ingested_at VARCHAR NOT NULL,
            source VARCHAR NOT NULL,
            payload JSON,
            metadata JSON
        )
        """
    )

    row_id = str(uuid.uuid4())
    try:
        conn.execute(
            f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?)",  # noqa: S608
            [row_id, tenant_id, _now(), source, json.dumps(data), json.dumps(metadata)],
        )
    except Exception as exc:
        return {
            "rows_received": 1,
            "rows_landed": 0,
            "target_table": table,
            "errors": [str(exc)],
        }

    return {"rows_received": 1, "rows_landed": 1, "target_table": table, "errors": []}


def land_batch_csv(
    source: str,
    content: bytes,
    tenant_id: str,
) -> dict[str, Any]:
    """Parse a CSV upload and land rows into the bronze layer."""
    conn = get_conn()
    table = _bronze_table(source)
    _ensure_bronze_schema(conn)
    text = content.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)

    if not rows:
        return {
            "rows_received": 0,
            "rows_landed": 0,
            "target_table": table,
            "errors": [],
        }

    raw_cols = list(rows[0].keys())
    cols = [_safe_col(c) for c in raw_cols]
    col_defs = ", ".join(f"{c} VARCHAR" for c in cols)
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
            _id VARCHAR PRIMARY KEY,
            _tenant_id VARCHAR NOT NULL,
            _ingested_at VARCHAR NOT NULL,
            {col_defs}
        )
        """
    )

    errors: list[str] = []
    landed = 0
    placeholders = ", ".join("?" * (len(cols) + 3))
    for i, row in enumerate(rows):
        try:
            values = [str(uuid.uuid4()), tenant_id, _now()] + [
                row.get(c, "") for c in raw_cols
            ]
            conn.execute(
                f"INSERT INTO {table} VALUES ({placeholders})", values
            )  # noqa: S608
            landed += 1
        except Exception as exc:
            errors.append(f"Row {i}: {exc}")

    return {
        "rows_received": len(rows),
        "rows_landed": landed,
        "target_table": table,
        "errors": errors,
    }


def land_batch_json(
    source: str,
    content: bytes,
    tenant_id: str,
) -> dict[str, Any]:
    """Parse a JSON upload (array or newline-delimited) and land into bronze."""
    text = content.decode("utf-8", errors="replace")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
    except json.JSONDecodeError:
        data = [json.loads(line) for line in text.splitlines() if line.strip()]

    results = []
    for record in data:
        result = land_webhook(source, record, {}, tenant_id)
        results.append(result)

    return {
        "rows_received": len(data),
        "rows_landed": sum(r["rows_landed"] for r in results),
        "target_table": _bronze_table(source),
        "errors": [],
    }
