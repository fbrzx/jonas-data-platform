"""Tenant-scoped DuckDB schema helpers.

Each tenant gets dedicated schemas for the data lake layers:
  bronze_{safe_id}, silver_{safe_id}, gold_{safe_id}

The safe_id replaces all non-alphanumeric characters in the tenant_id with underscores.
This means `tenant-acme` becomes `tenant_acme`, giving schemas like `bronze_tenant_acme`.
"""

import re
from typing import Any


def safe_tenant_id(tenant_id: str) -> str:
    """Return a DuckDB-safe slug from a tenant_id."""
    return re.sub(r"[^a-z0-9]", "_", tenant_id.lower())


def layer_schema(layer: str, tenant_id: str) -> str:
    """Return the tenant-scoped schema name for a data lake layer.

    Example: layer_schema("bronze", "tenant-acme") -> "bronze_tenant_acme"
    """
    return f"{layer}_{safe_tenant_id(tenant_id)}"


def provision_tenant_schemas(tenant_id: str) -> None:
    """Idempotently create all data lake schemas for a tenant."""
    from src.db.connection import get_conn

    conn = get_conn()
    for layer in ("bronze", "silver", "gold"):
        schema = layer_schema(layer, tenant_id)
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")  # noqa: S608
    print(f"[db.tenant_schemas] Provisioned schemas for tenant '{tenant_id}'")


def strip_tenant_schemas(sql: str) -> str:
    """Remove tenant-scoped schema prefixes so SQL uses bare layer names.

    Reverses inject_tenant_schemas — converts
    ``bronze_tenant_acme.orders`` → ``bronze.orders``.

    Apply before storing exported transform SQL so collections are portable
    across tenants.  inject_tenant_schemas then re-applies the correct
    target-tenant prefix at execution time.
    """
    return re.sub(
        r"\b(bronze|silver|gold)_[a-z0-9_]+\.",
        r"\1.",
        sql,
        flags=re.IGNORECASE,
    )


def inject_tenant_schemas(sql: str, tenant_id: str) -> str:
    """Rewrite bare layer.table references to tenant-scoped schemas.

    Transforms: `FROM bronze.orders` -> `FROM bronze_tenant_acme.orders`
    This is applied at execution time so stored SQL stays readable.
    Only rewrites `bronze.`, `silver.`, `gold.` when NOT already prefixed
    with a tenant suffix (i.e. not already `bronze_tenant_acme.`).
    """
    safe_id = safe_tenant_id(tenant_id)
    for layer in ("bronze", "silver", "gold"):
        # Match `bronze.` only when not already tenant-scoped (`bronze_something.`)
        sql = re.sub(
            rf"\b{layer}(?!_)\.",
            f"{layer}_{safe_id}.",
            sql,
            flags=re.IGNORECASE,
        )
    return sql


def table_ref(layer: str, name: str, tenant_id: str) -> str:
    """Return a fully-qualified DuckDB table reference for a tenant-scoped table."""
    return f"{layer_schema(layer, tenant_id)}.{name}"


def get_all_tenant_ids(conn: Any) -> list[str]:
    """Return all tenant IDs from the platform schema."""
    rows = conn.execute("SELECT id FROM platform.tenant").fetchall()
    return [r[0] for r in rows]
