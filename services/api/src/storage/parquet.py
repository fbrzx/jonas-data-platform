"""Parquet backup storage.

Mirrors DuckDB data to the configured storage root after every ingest and
transform execution.  The root can be a local path or a cloud prefix:

  Local:  "data/parquet"           (default)
  S3:     "s3://bucket/jonas"      (set S3_ACCESS_KEY + S3_SECRET_KEY)
  MinIO:  "s3://bucket/jonas"      (set S3_ENDPOINT to http://minio:9000)

Directory layout (tenant-scoped, forward-compatible with future primary-store
migration):

    {root}/{tenant_id}/
        bronze/{entity}/          ← append — one file per ingest batch
            {ISO-timestamp}.parquet
        silver/{entity}/          ← replace — latest snapshot
            latest.parquet
        gold/{entity}/            ← replace — latest snapshot
            latest.parquet
        runs/
            connectors/{connector_id}/   ← append audit trail
                {ISO-timestamp}.parquet
            transforms/{transform_id}/   ← append audit trail
                {ISO-timestamp}.parquet

All exports use DuckDB's native COPY … TO … (FORMAT PARQUET) so they are
efficient and produce proper column types.  Failures are logged but never
raise — the primary DuckDB store is unaffected.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _root_str() -> str:
    from src.config import settings

    return settings.parquet_root


def _is_cloud(root: str) -> bool:
    return root.startswith("s3://") or root.startswith("gs://")


def _ts() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S")


def _safe(name: str) -> str:
    """Sanitise a name for use as a directory/file component."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def _ensure_local_dir(path: str) -> None:
    """Create parent directories for a local path (no-op for cloud paths)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)


def _entity_path(tenant_id: str, layer: str, entity_name: str, filename: str) -> str:
    root = _root_str()
    return f"{root}/{_safe(tenant_id)}/{layer}/{_safe(entity_name)}/{filename}"


def _run_path(tenant_id: str, kind: str, resource_id: str, filename: str) -> str:
    root = _root_str()
    return f"{root}/{_safe(tenant_id)}/runs/{kind}/{_safe(resource_id)}/{filename}"


def _safe_s3_value(value: str) -> str:
    """Sanitise an S3 config value before interpolation into a DuckDB SET statement.

    DuckDB does not support parameterised SET, so we strip characters that could
    break the SQL string literal (single quotes, backslashes, newlines).
    """
    return value.replace("'", "").replace("\\", "").replace("\n", "").replace("\r", "")


def _configure_s3(conn: Any) -> None:
    """Install and configure DuckDB httpfs for S3/MinIO access."""
    from src.config import settings

    try:
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        conn.execute(f"SET s3_region='{_safe_s3_value(settings.s3_region)}';")
        if settings.s3_access_key:
            conn.execute(
                f"SET s3_access_key_id='{_safe_s3_value(settings.s3_access_key)}';"
            )
            conn.execute(
                f"SET s3_secret_access_key='{_safe_s3_value(settings.s3_secret_key)}';"
            )
        if settings.s3_endpoint:
            # MinIO / custom endpoint: disable SSL + path-style access
            conn.execute(
                f"SET s3_endpoint='{_safe_s3_value(settings.s3_endpoint.rstrip('/'))}/';"
            )
            conn.execute("SET s3_use_ssl=false;")
            conn.execute("SET s3_url_style='path';")
    except Exception as exc:
        logger.warning("[parquet] S3 httpfs setup failed: %s", exc)


# ── Public API ─────────────────────────────────────────────────────────────────


def export_bronze(
    tenant_id: str,
    entity_name: str,
    table_ref: str,  # fully-qualified DuckDB table, e.g. bronze_acme.orders
    conn: Any,
) -> str | None:
    """Export the current bronze table to a timestamped parquet file.

    Bronze is append-only so each call produces a new file — callers can glob
    the directory to reconstruct the full history.

    Returns the path/URI of the written file, or None on failure.
    """
    out_path = _entity_path(tenant_id, "bronze", entity_name, f"{_ts()}.parquet")
    return _copy_to(conn, table_ref, out_path)


def export_layer(
    tenant_id: str,
    layer: str,  # "silver" or "gold"
    entity_name: str,
    table_ref: str,
    conn: Any,
) -> str | None:
    """Export a silver/gold table to latest.parquet (replace on each run)."""
    out_path = _entity_path(tenant_id, layer, entity_name, "latest.parquet")
    return _copy_to(conn, table_ref, out_path)


def export_run(
    tenant_id: str,
    kind: str,  # "connectors" or "transforms"
    resource_id: str,
    record: dict[str, Any],
    conn: Any,
) -> str | None:
    """Append a single run record to the audit parquet trail."""
    import json

    out_path = _run_path(tenant_id, kind, resource_id, f"{_ts()}.parquet")

    # Serialise the record to a single-row parquet via a DuckDB VALUES query.
    safe: dict[str, str | int | float | None] = {}
    for k, v in record.items():
        if isinstance(v, (str, int, float)) or v is None:
            safe[k] = v
        else:
            safe[k] = json.dumps(v, default=str)

    cols = ", ".join(f'"{k}"' for k in safe)
    vals = ", ".join(
        "NULL"
        if v is None
        else f"'{str(v).replace(chr(39), chr(39)*2)}'"
        if isinstance(v, str)
        else str(v)
        for v in safe.values()
    )
    inline_sql = f"SELECT {cols} FROM (VALUES ({vals})) AS t({cols})"  # noqa: S608
    return _copy_to(conn, inline_sql, out_path, is_query=True)


# ── Internal ───────────────────────────────────────────────────────────────────


def _copy_to(
    conn: Any, source: str, out_path: str, *, is_query: bool = False
) -> str | None:
    """Run ``COPY … TO out_path (FORMAT PARQUET)``.

    ``source`` is either a table reference (``schema.table``) or a full SELECT
    query when ``is_query=True``.
    """
    root = _root_str()
    cloud = _is_cloud(root)

    if cloud:
        _configure_s3(conn)
    else:
        _ensure_local_dir(out_path)

    select_expr = source if is_query else f"SELECT * FROM {source}"  # noqa: S608
    try:
        conn.execute(
            f"COPY ({select_expr}) TO '{out_path}' (FORMAT PARQUET)"  # noqa: S608
        )
        logger.debug("[parquet] wrote → %s", out_path)
        return out_path
    except Exception as exc:
        logger.warning("[parquet] export failed → %s: %s", out_path, exc)
        return None
