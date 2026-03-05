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
            "Returns integration names, connector types, statuses, and IDs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "ingest_webhook",
        "description": (
            "Send a data payload into the bronze layer via webhook ingestion. "
            "Prefer supplying integration_id (from list_integrations or create_integration) "
            "so the source table is automatically derived from the integration's name. "
            "Fall back to an explicit source name only when no integration exists. "
            "Always confirm the data and target with the user before ingesting."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "integration_id": {
                    "type": "string",
                    "description": (
                        "UUID of an existing webhook integration. "
                        "When provided, the integration's name is used as the bronze table source — "
                        "no need to specify source separately."
                    ),
                },
                "source": {
                    "type": "string",
                    "description": (
                        "Fallback source identifier (snake_case) used as the bronze table name "
                        "when integration_id is not available."
                    ),
                },
                "data": {
                    "description": "The payload to land: a JSON object or array of objects",
                },
                "metadata": {
                    "type": "object",
                    "description": "Optional key-value metadata to attach to the record",
                },
            },
            "required": ["data"],
        },
    },
    {
        "name": "create_integration",
        "description": (
            "Register a new data integration (e.g. webhook receiver or batch upload source). "
            "When creating an integration for an existing catalogue entity, pass entity_id so the "
            "integration is linked: the entity's name becomes the canonical bronze table source, "
            "and preview_entity will query the same table that webhook data lands in. "
            "Requires admin or analyst role. Always confirm with the user before creating."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Short name for the integration (snake_case)",
                },
                "description": {
                    "type": "string",
                    "description": "What this integration ingests",
                },
                "connector_type": {
                    "type": "string",
                    "enum": ["webhook", "batch_csv", "batch_json"],
                    "description": "How data arrives",
                },
                "entity_id": {
                    "type": "string",
                    "description": (
                        "UUID of the catalogue entity this integration feeds. "
                        "When set, the integration name is ignored for routing — "
                        "the entity's name is used as the bronze table source instead, "
                        "so catalogue metadata, preview, and ingest all refer to the same table."
                    ),
                },
                "config": {
                    "type": "object",
                    "description": "Connector-specific configuration (e.g. source URL, auth)",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional labels for grouping",
                },
            },
            "required": ["name", "connector_type"],
        },
    },
    # ── Transforms ───────────────────────────────────────────────────────────
    {
        "name": "draft_transform",
        "description": (
            "Create a SQL transform draft that moves data between medallion layers "
            "(bronze→silver or silver→gold). The transform is saved with status=draft "
            "and requires admin approval before it can execute."
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
]
