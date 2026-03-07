"""Parquet backup storage.

Mirrors DuckDB data to the local filesystem after every ingest and transform
execution.  Directory layout (tenant-scoped, forward-compatible with future
primary-store migration):

    {parquet_root}/{tenant_id}/
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


def _root() -> Path:
    from src.config import settings

    return Path(settings.parquet_root)


def _ts() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S")


def _safe(name: str) -> str:
    """Sanitise a name for use as a directory/file component."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def entity_dir(tenant_id: str, layer: str, entity_name: str) -> Path:
    return _root() / _safe(tenant_id) / layer / _safe(entity_name)


def run_dir(tenant_id: str, kind: str, resource_id: str) -> Path:
    return _root() / _safe(tenant_id) / "runs" / kind / _safe(resource_id)


# ── Public API ─────────────────────────────────────────────────────────────────


def export_bronze(
    tenant_id: str,
    entity_name: str,
    table_ref: str,  # fully-qualified DuckDB table, e.g. bronze_acme.orders
    conn: Any,
) -> Path | None:
    """Export the current bronze table to a timestamped parquet file.

    Bronze is append-only so each call produces a new file — callers can glob
    the directory to reconstruct the full history.
    """
    out_dir = entity_dir(tenant_id, "bronze", entity_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_ts()}.parquet"
    try:
        conn.execute(
            f"COPY (SELECT * FROM {table_ref}) TO '{out_path}' (FORMAT PARQUET)"  # noqa: S608
        )
        logger.debug("[parquet] bronze export → %s", out_path)
        return out_path
    except Exception as exc:
        logger.warning("[parquet] bronze export failed for %s: %s", table_ref, exc)
        return None


def export_layer(
    tenant_id: str,
    layer: str,  # "silver" or "gold"
    entity_name: str,
    table_ref: str,
    conn: Any,
) -> Path | None:
    """Export a silver/gold table to latest.parquet (replace on each run)."""
    out_dir = entity_dir(tenant_id, layer, entity_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "latest.parquet"
    try:
        conn.execute(
            f"COPY (SELECT * FROM {table_ref}) TO '{out_path}' (FORMAT PARQUET)"  # noqa: S608
        )
        logger.debug("[parquet] %s export → %s", layer, out_path)
        return out_path
    except Exception as exc:
        logger.warning("[parquet] %s export failed for %s: %s", layer, table_ref, exc)
        return None


def export_run(
    tenant_id: str,
    kind: str,  # "connectors" or "transforms"
    resource_id: str,
    record: dict[str, Any],
    conn: Any,
) -> Path | None:
    """Append a single run record to the audit parquet trail."""
    import json

    out_dir = run_dir(tenant_id, kind, resource_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_ts()}.parquet"
    try:
        # Serialise the record to a single-row parquet via a DuckDB VALUES query.
        # JSON-encode complex values so every column is a scalar.
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
        conn.execute(
            f"COPY (SELECT {cols} FROM (VALUES ({vals})) AS t({cols})) "  # noqa: S608
            f"TO '{out_path}' (FORMAT PARQUET)"
        )
        logger.debug("[parquet] run export → %s", out_path)
        return out_path
    except Exception as exc:
        logger.warning(
            "[parquet] run export failed (%s/%s): %s", kind, resource_id, exc
        )
        return None
