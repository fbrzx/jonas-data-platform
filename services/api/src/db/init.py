"""Database + schema bootstrapping.

Runs the DuckDB DDL migration against the active connection (local or MotherDuck).
The DDL file itself creates all required schemas (platform, catalogue, transforms,
integrations, permissions, audit, bronze, silver, gold).
"""

import pathlib
from datetime import UTC, datetime

from src.db.connection import get_conn

_DDL_FILENAME = "001_core_duckdb.sql"

_ORDERS_JSON_TRANSFORM_SQL = """CREATE OR REPLACE TABLE silver.orders_cleaned AS
WITH parsed AS (
    SELECT
        json_extract_string(payload, '$.order_id') AS order_id,
        json_extract_string(payload, '$.customer_id') AS customer_id,
        json_extract_string(payload, '$.status') AS status,
        TRY_CAST(json_extract_string(payload, '$.created_at') AS TIMESTAMP) AS created_at,
        COALESCE(NULLIF(json_extract_string(payload, '$.shipping_country'), ''), 'UNKNOWN') AS shipping_country,
        TRY_CAST(json_extract(payload, '$.total') AS DOUBLE) AS total_usd
    FROM bronze.orders
)
SELECT
    order_id,
    customer_id,
    status,
    created_at,
    shipping_country,
    total_usd
FROM parsed
WHERE order_id IS NOT NULL AND total_usd IS NOT NULL"""


def _find_ddl() -> pathlib.Path:
    """Search upward from this file for db/001_core_duckdb.sql.

    Works in both layouts:
      Docker:   /app/src/db/init.py  → /app/db/
      Local dev: services/api/src/db/init.py → jonas-data-platform/db/
    """
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "db" / _DDL_FILENAME
        if candidate.exists():
            return candidate
    # Explicit fallback for Docker image layout
    return pathlib.Path("/app/db") / _DDL_FILENAME


def _migrate_legacy_orders_transform_sql() -> None:
    """Update older demo transform SQL that assumes flat bronze.orders columns.

    Older seed data stored raw JSON in bronze.orders(payload), but the transform
    used `order_id`/`total` columns directly. This migration rewrites only the
    legacy SQL signature to a payload-extraction variant.
    """
    conn = get_conn()
    now = datetime.now(UTC).isoformat()
    try:
        conn.execute(
            """
            UPDATE transforms.transform
            SET transform_sql = ?, updated_at = ?
            WHERE name = 'orders_bronze_to_silver'
              AND lower(transform_sql) LIKE ?
              AND lower(transform_sql) LIKE ?
              AND lower(transform_sql) NOT LIKE ?
            """,
            [
                _ORDERS_JSON_TRANSFORM_SQL,
                now,
                "%from bronze.orders%",
                "%where order_id is not null and total is not null%",
                "%json_extract%",
            ],
        )
    except Exception as exc:
        print(f"[db.init] Legacy transform SQL migration skipped: {exc!r}")


def bootstrap() -> None:
    """Idempotently run DDL migrations against the active connection."""
    conn = get_conn()
    DDL_PATH = _find_ddl()

    if not DDL_PATH.exists():
        print(f"[db.init] DDL file not found at {DDL_PATH} — skipping")
        return

    ddl = DDL_PATH.read_text()
    # DuckDB execexecutemany doesn't handle multi-statement strings well;
    # split on semicolons and execute each statement individually.
    statements = [s.strip() for s in ddl.split(";") if s.strip()]
    for stmt in statements:
        try:
            conn.execute(stmt)
        except Exception as exc:
            print(f"[db.init] Warning: {exc!r} for statement starting: {stmt[:60]!r}")

    _migrate_legacy_orders_transform_sql()

    print(f"[db.init] Bootstrap complete ({len(statements)} statements)")
