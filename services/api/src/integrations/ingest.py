"""Inbound ingestion: webhook + batch upload → bronze layer."""

import csv
import io
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from src.db.connection import get_conn
from src.db.tenant_schemas import layer_schema, safe_tenant_id
from src.transforms.triggers import fire_on_data_changed


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _record_run(
    integration_id: str | None,
    status: str,
    started_at: str,
    records_in: int,
    records_out: int,
    records_rejected: int,
    errors: list[str],
) -> str | None:
    """Write a run record to integration_run. Returns the run id, or None if skipped."""
    if not integration_id:
        return None
    conn = get_conn()
    run_id = str(uuid.uuid4())
    error_detail = json.dumps({"errors": errors}) if errors else json.dumps({})
    try:
        conn.execute(
            """
            INSERT INTO integrations.connector_run
                (id, integration_id, status, started_at, completed_at,
                 records_in, records_out, records_rejected, error_detail, stats)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                run_id,
                integration_id,
                status,
                started_at,
                _now(),
                records_in,
                records_out,
                records_rejected,
                error_detail,
                json.dumps({}),
            ],
        )
    except Exception:
        return None
    return run_id


def _bronze_table(source: str, tenant_id: str) -> str:
    """Derive a tenant-scoped safe bronze table name from the source identifier."""
    safe = "".join(c if c.isalnum() else "_" for c in source.lower())
    return f"{layer_schema('bronze', tenant_id)}.{safe}"


def _safe_col(name: str) -> str:
    """Sanitize a CSV column name for use as a SQL identifier."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name)


def _ensure_bronze_schema(conn: Any, tenant_id: str) -> None:
    schema = f"bronze_{safe_tenant_id(tenant_id)}"
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")  # noqa: S608


def land_webhook(
    source: str,
    data: dict[str, Any] | list[Any],
    metadata: dict[str, Any],
    tenant_id: str,
    integration_id: str | None = None,
    _fire_trigger: bool = True,
) -> dict[str, Any]:
    """Land a webhook payload into the bronze layer."""
    conn = get_conn()
    table = _bronze_table(source, tenant_id)
    _ensure_bronze_schema(conn, tenant_id)
    started_at = _now()

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
        run_id = _record_run(integration_id, "failed", started_at, 1, 0, 1, [str(exc)])
        return {
            "rows_received": 1,
            "rows_landed": 0,
            "target_table": table,
            "errors": [str(exc)],
            "run_id": run_id,
        }

    run_id = _record_run(integration_id, "success", started_at, 1, 1, 0, [])
    from src.storage.parquet import export_bronze

    export_bronze(tenant_id, source, table, conn)
    if _fire_trigger:
        fire_on_data_changed(source, "bronze", tenant_id)
    return {
        "rows_received": 1,
        "rows_landed": 1,
        "target_table": table,
        "errors": [],
        "run_id": run_id,
    }


def land_batch_csv(
    source: str,
    content: bytes,
    tenant_id: str,
    integration_id: str | None = None,
) -> dict[str, Any]:
    """Parse a CSV upload and land rows into the bronze layer."""
    conn = get_conn()
    table = _bronze_table(source, tenant_id)
    _ensure_bronze_schema(conn, tenant_id)
    started_at = _now()
    text = content.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)

    if not rows:
        run_id = _record_run(integration_id, "success", started_at, 0, 0, 0, [])
        return {
            "rows_received": 0,
            "rows_landed": 0,
            "target_table": table,
            "errors": [],
            "run_id": run_id,
        }

    raw_cols = list(rows[0].keys())  # type: ignore[union-attr]
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

    rejected = len(rows) - landed
    status = "success" if not errors else ("partial" if landed > 0 else "failed")
    run_id = _record_run(
        integration_id, status, started_at, len(rows), landed, rejected, errors
    )
    if landed > 0:
        from src.storage.parquet import export_bronze

        export_bronze(tenant_id, source, table, conn)
        fire_on_data_changed(source, "bronze", tenant_id)
    return {
        "rows_received": len(rows),
        "rows_landed": landed,
        "target_table": table,
        "errors": errors,
        "run_id": run_id,
    }


def land_api_pull(
    url: str,
    headers: dict[str, str],
    source: str,
    tenant_id: str,
    integration_id: str | None = None,
) -> dict[str, Any]:
    """Fetch JSON from a remote URL and land the result into the bronze layer."""
    import httpx

    started_at = _now()

    ssrf_err = check_url(url)
    if ssrf_err:
        run_id = _record_run(integration_id, "failed", started_at, 0, 0, 0, [ssrf_err])
        return {
            "rows_received": 0,
            "rows_landed": 0,
            "target_table": _bronze_table(source, tenant_id),
            "errors": [ssrf_err],
            "run_id": run_id,
        }

    try:
        # follow_redirects=False prevents SSRF bypass via open redirects
        response = httpx.get(url, headers=headers, timeout=30, follow_redirects=False)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        msg = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        run_id = _record_run(integration_id, "failed", started_at, 0, 0, 0, [msg])
        return {
            "rows_received": 0,
            "rows_landed": 0,
            "target_table": _bronze_table(source, tenant_id),
            "errors": [msg],
            "run_id": run_id,
        }
    except Exception as exc:
        msg = str(exc)
        run_id = _record_run(integration_id, "failed", started_at, 0, 0, 0, [msg])
        return {
            "rows_received": 0,
            "rows_landed": 0,
            "target_table": _bronze_table(source, tenant_id),
            "errors": [msg],
            "run_id": run_id,
        }

    try:
        data = response.json()
    except Exception as exc:
        msg = f"Response is not valid JSON: {exc}"
        run_id = _record_run(integration_id, "failed", started_at, 0, 0, 0, [msg])
        return {
            "rows_received": 0,
            "rows_landed": 0,
            "target_table": _bronze_table(source, tenant_id),
            "errors": [msg],
            "run_id": run_id,
        }

    # Normalise to a list of records
    records: list[Any] = data if isinstance(data, list) else [data]

    all_errors: list[str] = []
    total_landed = 0
    for record in records:
        result = land_webhook(
            source, record, {"pulled_from": url}, tenant_id, _fire_trigger=False
        )
        total_landed += result["rows_landed"]
        all_errors.extend(result.get("errors", []))

    rejected = len(records) - total_landed
    status = (
        "success" if not all_errors else ("partial" if total_landed > 0 else "failed")
    )
    run_id = _record_run(
        integration_id,
        status,
        started_at,
        len(records),
        total_landed,
        rejected,
        all_errors,
    )
    if total_landed > 0:
        fire_on_data_changed(source, "bronze", tenant_id)
    return {
        "rows_received": len(records),
        "rows_landed": total_landed,
        "target_table": _bronze_table(source, tenant_id),
        "errors": all_errors,
        "run_id": run_id,
    }


def land_batch_json(
    source: str,
    content: bytes,
    tenant_id: str,
    integration_id: str | None = None,
) -> dict[str, Any]:
    """Parse a JSON upload (array or newline-delimited) and land into bronze."""
    started_at = _now()
    text = content.decode("utf-8", errors="replace")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
    except json.JSONDecodeError:
        data = [json.loads(line) for line in text.splitlines() if line.strip()]

    all_errors: list[str] = []
    total_landed = 0
    for record in data:
        result = land_webhook(source, record, {}, tenant_id, _fire_trigger=False)
        total_landed += result["rows_landed"]
        all_errors.extend(result.get("errors", []))

    rejected = len(data) - total_landed
    status = (
        "success" if not all_errors else ("partial" if total_landed > 0 else "failed")
    )
    run_id = _record_run(
        integration_id,
        status,
        started_at,
        len(data),
        total_landed,
        rejected,
        all_errors,
    )
    if total_landed > 0:
        fire_on_data_changed(source, "bronze", tenant_id)
    return {
        "rows_received": len(data),
        "rows_landed": total_landed,
        "target_table": _bronze_table(source, tenant_id),
        "errors": all_errors,
        "run_id": run_id,
    }
