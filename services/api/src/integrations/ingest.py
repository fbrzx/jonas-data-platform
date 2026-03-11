"""Inbound ingestion: webhook + batch upload → bronze layer."""

import csv
import io
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from src.db.connection import get_conn
from src.db.tenant_schemas import layer_schema, safe_tenant_id
from src.security.oauth import resolve_headers as resolve_oauth_headers
from src.security.ssrf import check_url
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
    """Parse a CSV upload and land rows as JSON payloads into the bronze layer.

    Each CSV row is wrapped in the standard webhook format
    (id, tenant_id, ingested_at, source, payload JSON, metadata JSON)
    for uniform traceability across all ingestion types.
    """
    started_at = _now()
    text = content.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)

    if not rows:
        run_id = _record_run(integration_id, "success", started_at, 0, 0, 0, [])
        return {
            "rows_received": 0,
            "rows_landed": 0,
            "target_table": _bronze_table(source, tenant_id),
            "errors": [],
            "run_id": run_id,
        }

    all_errors: list[str] = []
    total_landed = 0
    for i, row in enumerate(rows):
        record = dict(row)
        result = land_webhook(
            source,
            record,
            {"format": "csv", "row_number": i},
            tenant_id,
            _fire_trigger=False,
        )
        total_landed += result["rows_landed"]
        if result.get("errors"):
            all_errors.extend(f"Row {i}: {e}" for e in result["errors"])

    rejected = len(rows) - total_landed
    status = (
        "success" if not all_errors else ("partial" if total_landed > 0 else "failed")
    )
    run_id = _record_run(
        integration_id, status, started_at, len(rows), total_landed, rejected, all_errors
    )
    if total_landed > 0:
        fire_on_data_changed(source, "bronze", tenant_id)
    return {
        "rows_received": len(rows),
        "rows_landed": total_landed,
        "target_table": _bronze_table(source, tenant_id),
        "errors": all_errors,
        "run_id": run_id,
    }


def _resolve_json_path(data: Any, path: str) -> Any:
    """Navigate a dot-notation path into nested dicts. e.g. 'data.items' → data['data']['items']."""
    if not path:
        return data
    for part in path.lstrip("$.").split("."):
        if isinstance(data, dict):
            data = data.get(part)
        else:
            return None
    return data


# Hard safety caps for pagination
_MAX_PAGES_CAP = 500
_MAX_RECORDS_CAP = 50_000


def _fetch_page(
    url: str,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
) -> Any:
    """Fetch a single page. Returns (response, data) or raises."""
    import httpx

    ssrf_err = check_url(url)
    if ssrf_err:
        raise ValueError(ssrf_err)

    response = httpx.get(
        url, headers=headers, params=params, timeout=30, follow_redirects=False
    )
    response.raise_for_status()
    return response


def land_api_pull(
    url: str,
    headers: dict[str, str],
    source: str,
    tenant_id: str,
    integration_id: str | None = None,
    json_path: str = "",
    pagination: dict[str, Any] | None = None,
    auth_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch JSON from a remote URL with optional pagination and land into bronze.

    Pagination strategies:
    - offset: increment offset_param by page_size each page
    - cursor: read cursor_path from response, send as cursor_param
    - link_header: follow Link rel="next" header
    - next_url: read next_url_path from response body
    """
    import re

    started_at = _now()
    table = _bronze_table(source, tenant_id)

    # Resolve OAuth token if auth_config specifies a grant_type.
    # Static Bearer tokens stored in config.headers continue to work unchanged.
    try:
        headers = resolve_oauth_headers(
            auth_config or {}, headers,
            integration_id=integration_id, tenant_id=tenant_id,
        )
    except Exception as exc:
        msg = f"OAuth token fetch failed: {exc}"
        run_id = _record_run(integration_id, "failed", started_at, 0, 0, 0, [msg])
        return {
            "rows_received": 0, "rows_landed": 0,
            "target_table": table, "errors": [msg], "run_id": run_id,
        }

    # base_url is used to resolve relative pagination URLs (e.g. Salesforce nextRecordsUrl)
    base_url = (auth_config or {}).get("base_url", "").rstrip("/")

    pagination = pagination or {}
    strategy = pagination.get("strategy", "")
    page_size = int(pagination.get("page_size", 100))
    max_pages = min(int(pagination.get("max_pages", 100)), _MAX_PAGES_CAP)

    all_errors: list[str] = []
    total_received = 0
    total_landed = 0
    page_num = 0

    try:
        if not strategy:
            # Single-page fetch (backward compatible)
            response = _fetch_page(url, headers)
            data = response.json()
            records = _resolve_json_path(data, json_path)
            if isinstance(records, dict):
                records = [records]
            if not isinstance(records, list):
                records = [data]

            for record in records:
                total_received += 1
                result = land_webhook(
                    source, record, {"pulled_from": url}, tenant_id, _fire_trigger=False
                )
                total_landed += result["rows_landed"]
                all_errors.extend(result.get("errors", []))

        elif strategy == "offset":
            offset_param = pagination.get("offset_param", "offset")
            limit_param = pagination.get("limit_param", "limit")
            offset = 0
            while page_num < max_pages and total_received < _MAX_RECORDS_CAP:
                params = {limit_param: page_size, offset_param: offset}
                response = _fetch_page(url, headers, params=params)
                data = response.json()
                records = _resolve_json_path(data, json_path)
                if not isinstance(records, list):
                    records = [records] if records else []
                if not records:
                    break
                for record in records:
                    total_received += 1
                    result = land_webhook(
                        source, record, {"pulled_from": url, "page": page_num},
                        tenant_id, _fire_trigger=False,
                    )
                    total_landed += result["rows_landed"]
                    all_errors.extend(result.get("errors", []))
                page_num += 1
                if len(records) < page_size:
                    break
                offset += page_size

        elif strategy == "cursor":
            cursor_param = pagination.get("cursor_param", "cursor")
            cursor_path = pagination.get("cursor_path", "meta.next_cursor")
            cursor_value: str | None = None
            while page_num < max_pages and total_received < _MAX_RECORDS_CAP:
                params: dict[str, Any] = {}
                if cursor_value:
                    params[cursor_param] = cursor_value
                response = _fetch_page(url, headers, params=params)
                data = response.json()
                records = _resolve_json_path(data, json_path)
                if not isinstance(records, list):
                    records = [records] if records else []
                if not records:
                    break
                for record in records:
                    total_received += 1
                    result = land_webhook(
                        source, record, {"pulled_from": url, "page": page_num},
                        tenant_id, _fire_trigger=False,
                    )
                    total_landed += result["rows_landed"]
                    all_errors.extend(result.get("errors", []))
                page_num += 1
                cursor_value = _resolve_json_path(data, cursor_path)
                if not cursor_value:
                    break

        elif strategy == "link_header":
            next_url: str | None = url
            while next_url and page_num < max_pages and total_received < _MAX_RECORDS_CAP:
                response = _fetch_page(next_url, headers)
                data = response.json()
                records = _resolve_json_path(data, json_path)
                if not isinstance(records, list):
                    records = [records] if records else []
                for record in records:
                    total_received += 1
                    result = land_webhook(
                        source, record, {"pulled_from": next_url, "page": page_num},
                        tenant_id, _fire_trigger=False,
                    )
                    total_landed += result["rows_landed"]
                    all_errors.extend(result.get("errors", []))
                page_num += 1
                link = response.headers.get("link", "")
                match = re.search(r'<([^>]+)>;\s*rel="next"', link)
                next_url = match.group(1) if match else None
                if next_url:
                    ssrf_err = check_url(next_url)
                    if ssrf_err:
                        all_errors.append(f"SSRF blocked next URL: {next_url}")
                        break

        elif strategy == "next_url":
            next_url_path = pagination.get("next_url_path", "next")
            current_url: str | None = url
            while current_url and page_num < max_pages and total_received < _MAX_RECORDS_CAP:
                response = _fetch_page(current_url, headers)
                data = response.json()
                records = _resolve_json_path(data, json_path)
                if not isinstance(records, list):
                    records = [records] if records else []
                for record in records:
                    total_received += 1
                    result = land_webhook(
                        source, record, {"pulled_from": current_url, "page": page_num},
                        tenant_id, _fire_trigger=False,
                    )
                    total_landed += result["rows_landed"]
                    all_errors.extend(result.get("errors", []))
                page_num += 1
                next_val = _resolve_json_path(data, next_url_path)
                if not next_val or not isinstance(next_val, str):
                    current_url = None
                else:
                    # Resolve relative paths (e.g. Salesforce "/services/data/vXX/query/...")
                    if next_val.startswith("/") and base_url:
                        next_val = f"{base_url}{next_val}"
                    ssrf_err = check_url(next_val)
                    if ssrf_err:
                        all_errors.append(f"SSRF blocked next URL: {next_val}")
                        current_url = None
                    else:
                        current_url = next_val

        else:
            all_errors.append(f"Unknown pagination strategy: {strategy}")

    except ValueError as exc:
        # SSRF or similar validation error
        msg = str(exc)
        run_id = _record_run(integration_id, "failed", started_at, 0, 0, 0, [msg])
        return {
            "rows_received": 0,
            "rows_landed": 0,
            "target_table": table,
            "errors": [msg],
            "run_id": run_id,
        }
    except Exception as exc:
        msg = str(exc)
        all_errors.append(msg)

    rejected = total_received - total_landed
    status = (
        "success" if not all_errors else ("partial" if total_landed > 0 else "failed")
    )
    run_id = _record_run(
        integration_id, status, started_at,
        total_received, total_landed, rejected, all_errors,
    )
    if total_landed > 0:
        fire_on_data_changed(source, "bronze", tenant_id)
    return {
        "rows_received": total_received,
        "rows_landed": total_landed,
        "target_table": table,
        "errors": all_errors,
        "run_id": run_id,
        "pages_fetched": max(page_num, 1) if not strategy else page_num,
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
