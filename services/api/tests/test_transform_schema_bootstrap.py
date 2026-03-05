"""Regression tests for transform schema bootstrap behavior."""

import duckdb
import pytest

from src.db import connection as db
from src.db.init import bootstrap
from src.transforms import service


@pytest.fixture(autouse=True)
def _init_db() -> None:
    """Use a clean in-memory DuckDB and run DDL bootstrap for each test."""
    db._conn = duckdb.connect(":memory:")
    bootstrap()
    yield
    db._conn.close()
    db._conn = None


def test_execute_transform_recreates_missing_target_schema() -> None:
    conn = db.get_conn()
    conn.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    conn.execute(
        "CREATE OR REPLACE TABLE bronze.orders (order_id VARCHAR, total DOUBLE)"
    )
    conn.execute("INSERT INTO bronze.orders VALUES ('o1', 10.0), ('o2', 25.5)")

    # Simulate a stale DB that predates medallion schema bootstrap.
    conn.execute("DROP SCHEMA IF EXISTS silver CASCADE")

    created = service.create_transform(
        {
            "name": "orders_cleaned",
            "description": "test transform",
            "source_layer": "bronze",
            "target_layer": "silver",
            "sql": (
                "CREATE OR REPLACE TABLE silver.orders_cleaned AS "
                "SELECT order_id, total AS total_usd FROM bronze.orders"
            ),
        },
        tenant_id="tenant-acme",
        created_by="user-admin",
    )

    approved = service.approve_transform(
        created["id"],
        action="approve",
        approved_by="user-admin",
        tenant_id="tenant-acme",
    )

    assert approved is not None
    assert approved["status"] == "approved"

    result = service.execute_transform(created["id"], tenant_id="tenant-acme")
    assert result["errors"] == []
    assert result["rows_affected"] == 2
    assert result["target_table"] == "silver.orders_cleaned"

    row = conn.execute("SELECT COUNT(*) FROM silver.orders_cleaned").fetchone()
    assert row is not None
    assert row[0] == 2
