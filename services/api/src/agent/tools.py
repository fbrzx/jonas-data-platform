"""Tool definitions exposed to the Claude agent."""

from typing import Any

TOOLS: list[dict[str, Any]] = [
    # ── Catalogue ────────────────────────────────────────────────────────────
    {
        "name": "list_entities",
        "description": (
            "List all data entities in the catalogue that the current user can access. "
            "Returns entity names, layers (bronze/silver/gold), descriptions, and IDs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "layer": {
                    "type": "string",
                    "enum": ["bronze", "silver", "gold"],
                    "description": "Filter to a specific layer",
                }
            },
            "required": [],
        },
    },
    {
        "name": "describe_entity",
        "description": (
            "Get the full schema for a specific entity: all fields with types, "
            "nullability, PII flags, and sample values."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "description": "UUID of the entity"}
            },
            "required": ["entity_id"],
        },
    },
    # ── Schema inference ─────────────────────────────────────────────────────
    {
        "name": "infer_schema",
        "description": (
            "Analyse a sample JSON payload or CSV rows and infer field definitions "
            "(name, data_type, nullable, is_pii). Use this before register_entity "
            "to propose a schema to the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sample": {
                    "description": "Sample data — a JSON object, array of objects,"
                    " or CSV rows as array of objects",
                },
                "format": {
                    "type": "string",
                    "enum": ["json", "csv"],
                    "description": "Format of the sample data",
                    "default": "json",
                },
            },
            "required": ["sample"],
        },
    },
    {
        "name": "register_entity",
        "description": (
            "Register a new entity (table) in the data catalogue with its field definitions. "
            "Use after infer_schema and user approval. "
            "Returns the created entity with its ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Table name (snake_case)"},
                "layer": {
                    "type": "string",
                    "enum": ["bronze", "silver", "gold"],
                    "description": "Medallion layer",
                },
                "description": {
                    "type": "string",
                    "description": "What this entity contains",
                },
                "namespace": {
                    "type": "string",
                    "description": "Logical grouping (e.g. ecommerce, iot, crm)",
                },
                "fields": {
                    "type": "array",
                    "description": "Field definitions from infer_schema",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "data_type": {
                                "type": "string",
                                "enum": [
                                    "string",
                                    "int",
                                    "float",
                                    "bool",
                                    "timestamp",
                                    "json",
                                    "array",
                                ],
                            },
                            "nullable": {"type": "boolean"},
                            "is_pii": {"type": "boolean"},
                            "description": {"type": "string"},
                        },
                        "required": ["name", "data_type"],
                    },
                },
            },
            "required": ["name", "layer", "fields"],
        },
    },
    # ── SQL ──────────────────────────────────────────────────────────────────
    {
        "name": "run_sql",
        "description": (
            "Execute a read-only SQL SELECT query against the DuckDB warehouse. "
            "PII fields are automatically masked based on the user's permissions. "
            "Only SELECT statements are allowed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "A DuckDB-compatible SELECT query",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rows to return (default 100, max 1000)",
                    "default": 100,
                },
            },
            "required": ["sql"],
        },
    },
    {
        "name": "preview_entity",
        "description": (
            "Show a sample of recent rows from an entity. "
            "PII fields are masked based on the user's permissions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "description": "UUID of the entity"},
                "limit": {
                    "type": "integer",
                    "description": "Number of rows to return (default 10, max 100)",
                    "default": 10,
                },
            },
            "required": ["entity_id"],
        },
    },
    # ── Integrations ─────────────────────────────────────────────────────────
    {
        "name": "list_integrations",
        "description": (
            "List all data integrations configured for the current tenant. "
            "Returns integration names, connector types (webhook/batch_csv/batch_json), "
            "statuses, linked entity IDs, and integration IDs. "
            "Call this first when the user wants to import data, to see what exists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_integration_runs",
        "description": (
            "Return the recent run history for a specific integration. "
            "Each run shows status (success/partial/failed), timestamps, "
            "records_in, records_out, records_rejected, and any error detail. "
            "Use this to diagnose import failures or confirm that data landed successfully."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "integration_id": {
                    "type": "string",
                    "description": "UUID of the integration",
                },
            },
            "required": ["integration_id"],
        },
    },
    {
        "name": "ingest_webhook",
        "description": (
            "Send a JSON data payload into the bronze layer via webhook ingestion. "
            "Step 1: call list_integrations to find or confirm the target integration. "
            "Step 2: if no integration exists, create one with create_integration first. "
            "Step 3: show the user exactly what data will be sent and to which table, "
            "then confirm. "
            "Step 4: call this tool with integration_id (preferred) or an explicit source name. "
            "The bronze table name is derived from the integration's linked entity name, "
            "or from the integration name if no entity is linked. "
            "After ingesting, call get_integration_runs to verify rows landed successfully."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "integration_id": {
                    "type": "string",
                    "description": (
                        "UUID of an existing webhook integration. "
                        "When provided, the source table is automatically derived — "
                        "no need to specify source separately."
                    ),
                },
                "source": {
                    "type": "string",
                    "description": (
                        "Fallback source identifier (snake_case, e.g. 'customer_events') "
                        "used as the bronze table name only when integration_id is not available."
                    ),
                },
                "data": {
                    "description": "The payload to land: a JSON object or array of objects",
                },
                "metadata": {
                    "type": "object",
                    "description": (
                        "Optional key-value metadata to attach to the record "
                        "(e.g. source_system, batch_id)"
                    ),
                },
            },
            "required": ["data"],
        },
    },
    {
        "name": "create_integration",
        "description": (
            "Register a new data integration (webhook receiver or batch file upload source). "
            "Choose connector_type based on how data will arrive:\n"
            "  - 'webhook': for real-time JSON events pushed via HTTP POST\n"
            "  - 'batch_csv': for periodic CSV file uploads (max 50 MB)\n"
            "  - 'batch_json': for periodic JSON file uploads (array or newline-delimited)\n"
            "When creating an integration for an existing catalogue entity, pass entity_id so "
            "the entity's name becomes the canonical bronze table — ingest and preview will "
            "always refer to the same table. If no entity exists yet, create one with "
            "register_entity first (infer_schema → register_entity → create_integration). "
            "Requires admin or analyst role. Always confirm the name, type, and linked entity "
            "with the user before creating."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Short snake_case name for the integration "
                        "(e.g. 'sales_orders_webhook')"
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "What data this integration ingests",
                },
                "connector_type": {
                    "type": "string",
                    "enum": ["webhook", "batch_csv", "batch_json", "api_pull"],
                    "description": (
                        "How data arrives: webhook (real-time JSON push), batch_csv, batch_json, "
                        "or api_pull (platform fetches from a remote URL on demand — "
                        "requires config.url)"
                    ),
                },
                "entity_id": {
                    "type": "string",
                    "description": (
                        "UUID of the catalogue entity this integration feeds into. "
                        "When set, the entity's name becomes the bronze table source, "
                        "so catalogue metadata, preview, and ingest all use the same table."
                    ),
                },
                "config": {
                    "type": "object",
                    "description": (
                        "Connector-specific config "
                        '(e.g. {"source_url": "...", "auth_header": "x-api-key"})'
                    ),
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional labels for grouping (e.g. ['ecommerce', 'realtime'])",
                },
            },
            "required": ["name", "connector_type"],
        },
    },
    # ── Transforms ───────────────────────────────────────────────────────────
    {
        "name": "list_transforms",
        "description": (
            "List all transform drafts and their status for the current tenant. "
            "Returns id, name, description, source_layer, target_layer, status, and transform_sql. "
            "Call this before draft_transform to check whether a transform already exists "
            "that you should update instead of creating a duplicate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "draft_transform",
        "description": (
            "Create a NEW SQL transform draft that moves data between medallion layers "
            "(bronze→silver or silver→gold). The transform is saved with status=draft "
            "and requires admin approval before it can execute. "
            "IMPORTANT: call list_transforms first — if a transform with the same name or "
            "purpose already exists, use update_transform instead to avoid duplicates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Short name for this transform (snake_case)",
                },
                "description": {
                    "type": "string",
                    "description": "What this transform does",
                },
                "source_layer": {
                    "type": "string",
                    "enum": ["bronze", "silver"],
                    "description": "Source medallion layer",
                },
                "target_layer": {
                    "type": "string",
                    "enum": ["silver", "gold"],
                    "description": "Target medallion layer",
                },
                "sql": {
                    "type": "string",
                    "description": "DuckDB SQL — typically a CREATE TABLE AS SELECT or INSERT INTO",
                },
            },
            "required": ["name", "sql", "source_layer", "target_layer"],
        },
    },
    {
        "name": "update_transform",
        "description": (
            "Update an existing transform draft — change its SQL, description, or layer settings. "
            "Only drafts can have their SQL/layers changed; approved/rejected transforms will be "
            "reset to draft status when SQL is modified (requiring re-approval). "
            "Use this instead of draft_transform when a transform already exists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "transform_id": {
                    "type": "string",
                    "description": "UUID of the transform to update",
                },
                "name": {"type": "string", "description": "New name (optional)"},
                "description": {
                    "type": "string",
                    "description": "New description (optional)",
                },
                "sql": {
                    "type": "string",
                    "description": "Updated DuckDB SQL (resets status to draft if not already)",
                },
                "source_layer": {
                    "type": "string",
                    "enum": ["bronze", "silver"],
                    "description": "Updated source layer (optional)",
                },
                "target_layer": {
                    "type": "string",
                    "enum": ["silver", "gold"],
                    "description": "Updated target layer (optional)",
                },
            },
            "required": ["transform_id"],
        },
    },
]
