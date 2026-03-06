#!/usr/bin/env python3
"""Seed the demo environment via the live API.

Requires the API to be running (default: http://localhost:8000).
Uses admin-token for all requests.

Steps:
  1. POST catalogue entities with field definitions
  2. POST integrations
  3. POST transforms (draft status)
  4. Ingest sample data files if present (run seed_data.py first)
"""

import sys
from pathlib import Path

import httpx

API_BASE = "http://localhost:8000/api/v1"
HEADERS = {"Authorization": "Bearer admin-token", "Content-Type": "application/json"}
SAMPLE_DIR = Path(__file__).parent.parent / "sample_data"


def api_get(path: str) -> list:
    r = httpx.get(f"{API_BASE}{path}", headers=HEADERS, timeout=15)
    if r.status_code == 200:
        data = r.json()
        return data if isinstance(data, list) else data.get("items", [])
    return []


def api_delete(path: str) -> None:
    httpx.delete(f"{API_BASE}{path}", headers=HEADERS, timeout=15)


def api_post(path: str, body: dict) -> dict:
    r = httpx.post(f"{API_BASE}{path}", json=body, headers=HEADERS, timeout=15)
    if r.status_code not in (200, 201):
        print(f"  ERROR {r.status_code} on POST {path}: {r.text[:200]}")
        return {}
    return r.json()


def wipe_existing() -> None:
    """Delete all existing catalogue entities, integrations, and transforms."""
    print("\n[0/3] Wiping existing data")
    for e in api_get("/catalogue/entities"):
        api_delete(f"/catalogue/entities/{e['id']}")
    for intg in api_get("/connectors"):
        api_delete(f"/connectors/{intg['id']}") 
    for t in api_get("/transforms"):
        api_delete(f"/transforms/{t['id']}")
    print("  ✓  wiped")


def ingest_batch(name: str, file_path: Path) -> None:
    if not file_path.exists():
        print(f"  SKIP {file_path.name} — run 'make seed' first")
        return
    suffix = file_path.suffix.lstrip(".")
    with file_path.open("rb") as fh:
        r = httpx.post(
            f"{API_BASE}/connectors/ingest/batch",
            params={"source": name},
            files={"file": (file_path.name, fh, f"text/{suffix}")},
            headers={"Authorization": "Bearer admin-token"},
            timeout=30,
        )
    if r.status_code in (200, 201):
        result = r.json()
        print(f"  ingested {result.get('rows_landed', '?')} rows → bronze")
    else:
        print(f"  ERROR {r.status_code}: {r.text[:200]}")


# ── Catalogue entities ────────────────────────────────────────────────────────

ENTITIES = [
    {
        "name": "orders",
        "layer": "bronze",
        "description": "Raw e-commerce orders with nested line items",
        "tags": ["ecommerce"],
        "fields": [
            {
                "name": "order_id",
                "data_type": "string",
                "nullable": False,
                "ordinal": 0,
            },
            {
                "name": "customer_id",
                "data_type": "string",
                "nullable": False,
                "ordinal": 1,
            },
            {"name": "status", "data_type": "string", "nullable": False, "ordinal": 2},
            {
                "name": "created_at",
                "data_type": "timestamp",
                "nullable": False,
                "ordinal": 3,
            },
            {
                "name": "shipping_country",
                "data_type": "string",
                "nullable": True,
                "ordinal": 4,
            },
            {
                "name": "currency",
                "data_type": "string",
                "nullable": False,
                "ordinal": 5,
            },
            {"name": "subtotal", "data_type": "float", "nullable": False, "ordinal": 6},
            {"name": "tax", "data_type": "float", "nullable": False, "ordinal": 7},
            {"name": "total", "data_type": "float", "nullable": False, "ordinal": 8},
            {"name": "line_items", "data_type": "json", "nullable": True, "ordinal": 9},
        ],
    },
    {
        "name": "sensor_readings",
        "layer": "bronze",
        "description": "IoT sensor readings — may contain invalid values",
        "tags": ["iot"],
        "fields": [
            {
                "name": "reading_id",
                "data_type": "string",
                "nullable": False,
                "ordinal": 0,
            },
            {
                "name": "device_id",
                "data_type": "string",
                "nullable": False,
                "ordinal": 1,
            },
            {
                "name": "sensor_type",
                "data_type": "string",
                "nullable": False,
                "ordinal": 2,
            },
            {"name": "value", "data_type": "string", "nullable": True, "ordinal": 3},
            {"name": "unit", "data_type": "string", "nullable": True, "ordinal": 4},
            {
                "name": "recorded_at",
                "data_type": "timestamp",
                "nullable": False,
                "ordinal": 5,
            },
            {"name": "location", "data_type": "string", "nullable": True, "ordinal": 6},
            {
                "name": "firmware_version",
                "data_type": "string",
                "nullable": True,
                "ordinal": 7,
            },
        ],
    },
    {
        "name": "contacts",
        "layer": "bronze",
        "description": "CRM contacts — contains PII fields",
        "tags": ["crm"],
        "fields": [
            {
                "name": "contact_id",
                "data_type": "string",
                "nullable": False,
                "ordinal": 0,
            },
            {
                "name": "first_name",
                "data_type": "string",
                "nullable": False,
                "is_pii": True,
                "ordinal": 1,
            },
            {
                "name": "last_name",
                "data_type": "string",
                "nullable": False,
                "is_pii": True,
                "ordinal": 2,
            },
            {
                "name": "email",
                "data_type": "string",
                "nullable": False,
                "is_pii": True,
                "ordinal": 3,
            },
            {"name": "company", "data_type": "string", "nullable": True, "ordinal": 4},
            {"name": "segment", "data_type": "string", "nullable": True, "ordinal": 5},
            {
                "name": "phone",
                "data_type": "string",
                "nullable": True,
                "is_pii": True,
                "ordinal": 6,
            },
            {
                "name": "linkedin_url",
                "data_type": "string",
                "nullable": True,
                "ordinal": 7,
            },
            {"name": "notes", "data_type": "string", "nullable": True, "ordinal": 8},
            {
                "name": "created_at",
                "data_type": "timestamp",
                "nullable": False,
                "ordinal": 9,
            },
        ],
    },
    {
        "name": "orders_cleaned",
        "layer": "silver",
        "description": "Validated orders — nulls resolved, types cast",
        "tags": ["ecommerce"],
        "fields": [
            {
                "name": "order_id",
                "data_type": "string",
                "nullable": False,
                "ordinal": 0,
            },
            {
                "name": "customer_id",
                "data_type": "string",
                "nullable": False,
                "ordinal": 1,
            },
            {"name": "status", "data_type": "string", "nullable": False, "ordinal": 2},
            {
                "name": "created_at",
                "data_type": "timestamp",
                "nullable": False,
                "ordinal": 3,
            },
            {
                "name": "shipping_country",
                "data_type": "string",
                "nullable": False,
                "ordinal": 4,
            },
            {
                "name": "total_usd",
                "data_type": "float",
                "nullable": False,
                "ordinal": 5,
            },
        ],
    },
    {
        "name": "revenue_by_country",
        "layer": "gold",
        "description": "Daily revenue aggregated by country",
        "tags": ["ecommerce", "reporting"],
        "fields": [
            {"name": "date", "data_type": "string", "nullable": False, "ordinal": 0},
            {"name": "country", "data_type": "string", "nullable": False, "ordinal": 1},
            {
                "name": "order_count",
                "data_type": "int",
                "nullable": False,
                "ordinal": 2,
            },
            {
                "name": "total_revenue",
                "data_type": "float",
                "nullable": False,
                "ordinal": 3,
            },
        ],
    },
]

# ── Integrations ──────────────────────────────────────────────────────────────

INTEGRATIONS = [
    {
        "name": "Orders Webhook",
        "description": "Receives order events from the e-commerce platform",
        "connector_type": "webhook",
        "config": {"target_table": "bronze.orders", "format": "json"},
    },
    {
        "name": "Sensor CSV Batch",
        "description": "Daily CSV export from IoT device management system",
        "connector_type": "batch_csv",
        "config": {"target_table": "bronze.sensor_readings", "schedule": "0 2 * * *"},
    },
    {
        "name": "CRM Contact Sync",
        "description": "Nightly JSON export of CRM contacts",
        "connector_type": "batch_json",
        "config": {"target_table": "bronze.contacts", "schedule": "0 1 * * *"},
    },
]

# ── Transforms ────────────────────────────────────────────────────────────────

TRANSFORMS = [
    {
        "name": "orders_bronze_to_silver",
        "description": "Clean and validate orders: resolve nulls, cast types",
        "source_layer": "bronze",
        "target_layer": "silver",
        "sql": (
            "CREATE OR REPLACE TABLE silver.orders_cleaned AS\n"
            "WITH parsed AS (\n"
            "    SELECT\n"
            "        json_extract_string(payload, '$.order_id') AS order_id,\n"
            "        json_extract_string(payload, '$.customer_id') AS customer_id,\n"
            "        json_extract_string(payload, '$.status') AS status,\n"
            "        TRY_CAST(json_extract_string(payload, '$.created_at') AS TIMESTAMP) AS created_at,\n"
            "        COALESCE(NULLIF(json_extract_string(payload, '$.shipping_country'), ''), 'UNKNOWN') AS shipping_country,\n"
            "        TRY_CAST(json_extract(payload, '$.total') AS DOUBLE) AS total_usd\n"
            "    FROM bronze.orders\n"
            ")\n"
            "SELECT\n"
            "    order_id,\n"
            "    customer_id,\n"
            "    status,\n"
            "    created_at,\n"
            "    shipping_country,\n"
            "    total_usd\n"
            "FROM parsed\n"
            "WHERE order_id IS NOT NULL AND total_usd IS NOT NULL"
        ),
        "tags": ["ecommerce"],
    },
    {
        "name": "revenue_by_country",
        "description": "Aggregate daily revenue by country for the gold layer",
        "source_layer": "silver",
        "target_layer": "gold",
        "sql": (
            "CREATE OR REPLACE TABLE gold.revenue_by_country AS\n"
            "SELECT\n"
            "    created_at::DATE AS date,\n"
            "    shipping_country AS country,\n"
            "    COUNT(*) AS order_count,\n"
            "    SUM(total_usd) AS total_revenue\n"
            "FROM silver.orders_cleaned\n"
            "GROUP BY 1, 2\n"
            "ORDER BY 1 DESC, 4 DESC"
        ),
        "tags": ["ecommerce", "reporting"],
    },
]


def create_entity_fields(entity_id: str, fields: list[dict]) -> int:
    """POST fields to the dedicated fields endpoint."""
    r = httpx.post(
        f"{API_BASE}/catalogue/entities/{entity_id}/fields",
        json=fields,
        headers=HEADERS,
        timeout=15,
    )
    if r.status_code == 201:
        return len(r.json())
    print(f"  WARN fields endpoint {r.status_code}: {r.text[:100]}")
    return 0


def main() -> None:
    print("\n🌱  Jonas Demo Seed")
    print("=" * 40)

    wipe_existing()

    # ── Catalogue ─────────────────────────────────────────────────────────────
    print("\n[1/3] Catalogue entities")
    for e in ENTITIES:
        fields = e.pop("fields", [])
        result = api_post("/catalogue/entities", e)
        if result.get("id"):
            field_count = create_entity_fields(result["id"], fields)
            print(f"  ✓  {e['layer']}.{e['name']} ({field_count} fields)")
        e["fields"] = fields  # restore

    # ── Integrations ──────────────────────────────────────────────────────────
    print("\n[2/3] Integrations")
    for intg in INTEGRATIONS:
        result = api_post("/connectors", intg)
        if result.get("id"):
            print(f"  ✓  {intg['name']}")

    # ── Transforms ────────────────────────────────────────────────────────────
    print("\n[3/3] Transforms")
    for t in TRANSFORMS:
        result = api_post("/transforms", t)
        if result.get("id"):
            print(f"  ✓  {t['name']} [{result.get('status')}]")

    # ── Ingest sample files ───────────────────────────────────────────────────
    print("\n[bonus] Ingesting sample data files")
    ingest_batch("orders", SAMPLE_DIR / "orders.json")
    ingest_batch("sensor_readings", SAMPLE_DIR / "sensor_readings.csv")
    ingest_batch("contacts", SAMPLE_DIR / "contacts.json")

    print("\n✅  Seed complete — open http://localhost:5173\n")


if __name__ == "__main__":
    try:
        httpx.get("http://localhost:8000/health", timeout=5).raise_for_status()
    except Exception:
        print("ERROR: API not reachable. Run 'make up' first.")
        sys.exit(1)

    main()
