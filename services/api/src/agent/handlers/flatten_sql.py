"""Generate bronze→silver flattening SQL from inferred schema."""

from __future__ import annotations

from src.db.tenant_schemas import layer_schema

# Map inference types to DuckDB types
_TYPE_MAP: dict[str, str] = {
    "string": "VARCHAR",
    "int": "BIGINT",
    "float": "DOUBLE",
    "bool": "BOOLEAN",
    "timestamp": "TIMESTAMP",
    "json": "JSON",
    "array": "JSON",
}

# Field names that hint at a primary key
_PK_SUFFIXES = ("_uuid", "_key", "_ref")
_PK_EXACT = {"id"}


def detect_primary_key(fields: list[dict], entity_name: str = "") -> str | None:
    """Guess the PK field from field names. Returns None if ambiguous."""
    names = [f["name"] for f in fields]

    # Exact "id" field
    if "id" in names:
        return "id"

    # Field named <entity_name>_id (e.g. entity "orders" → "order_id")
    if entity_name:
        singular = entity_name.rstrip("s")
        candidate = f"{singular}_id"
        if candidate in names:
            return candidate

    # First field ending in _id (excluding tenant_id, metadata ids)
    for n in names:
        if n.endswith("_id") and n not in ("tenant_id",):
            return n

    # UUID/key fields
    for n in names:
        if any(n.endswith(s) for s in _PK_SUFFIXES):
            return n

    return None


def generate_flatten_sql(
    entity_name: str,
    fields: list[dict],
    pk_field: str,
    tenant_id: str,
) -> str:
    """Generate the two-statement upsert SQL for bronze→silver flattening.

    Returns SQL in the mandatory format:
      CREATE TABLE IF NOT EXISTS silver.{name} (...);
      INSERT OR REPLACE INTO silver.{name} SELECT ... FROM bronze.{name};
    """
    silver = layer_schema("silver", tenant_id)
    bronze = layer_schema("bronze", tenant_id)

    # Statement 1: CREATE TABLE IF NOT EXISTS
    col_defs: list[str] = []
    for f in fields:
        ddb_type = _TYPE_MAP.get(f.get("data_type", "string"), "VARCHAR")
        pk = " PRIMARY KEY" if f["name"] == pk_field else ""
        col_defs.append(f"    {f['name']} {ddb_type}{pk}")

    create_stmt = (
        f"CREATE TABLE IF NOT EXISTS {silver}.{entity_name} (\n"
        + ",\n".join(col_defs)
        + "\n)"
    )

    # Statement 2: INSERT OR REPLACE with json_extract from payload
    select_cols: list[str] = []
    for f in fields:
        dt = f.get("data_type", "string")
        name = f["name"]
        if dt in ("int", "float", "bool", "timestamp"):
            ddb_type = _TYPE_MAP[dt]
            select_cols.append(
                f"    TRY_CAST(json_extract(payload, '$.{name}') AS {ddb_type}) AS {name}"
            )
        else:
            select_cols.append(
                f"    json_extract_string(payload, '$.{name}') AS {name}"
            )

    insert_stmt = (
        f"INSERT OR REPLACE INTO {silver}.{entity_name}\n"
        "SELECT\n" + ",\n".join(select_cols) + f"\nFROM {bronze}.{entity_name}\n"
        f"WHERE json_extract_string(payload, '$.{pk_field}') IS NOT NULL"
    )

    return f"{create_stmt};\n\n{insert_stmt};"
