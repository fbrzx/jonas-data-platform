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
    # ── Connectors ───────────────────────────────────────────────────────────
    {
        "name": "list_connectors",
        "description": (
            "List all data connectors configured for the current tenant. "
            "Returns connector names, types (webhook/batch_csv/batch_json/api_pull), "
            "statuses, linked entity IDs, and connector IDs. "
            "Call this first when the user wants to import data, to see what exists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_connector_runs",
        "description": (
            "Return the recent run history for a specific connector. "
            "Each run shows status (success/partial/failed), timestamps, "
            "records_in, records_out, records_rejected, and any error detail. "
            "Use this to diagnose import failures or confirm that data landed successfully."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "connector_id": {
                    "type": "string",
                    "description": "UUID of the connector",
                },
            },
            "required": ["connector_id"],
        },
    },
    {
        "name": "discover_api",
        "description": (
            "Perform a single HTTP request to an external API and return the raw response "
            "for schema inference. Use this to explore an API before creating a connector. "
            "SSRF-protected: only public http/https URLs are allowed. "
            "Returns sample records (up to 5) and total record count."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL to fetch"},
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT"],
                    "description": "HTTP method (default: GET)",
                },
                "headers": {
                    "type": "object",
                    "description": 'Request headers (e.g. {"Authorization": "Bearer token"})',
                },
                "body": {
                    "type": "object",
                    "description": "Request body for POST/PUT",
                },
                "json_path": {
                    "type": "string",
                    "description": "Dot-notation path to the records array in the response"
                    " (e.g. 'data.items')",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "ingest_webhook",
        "description": (
            "Send a JSON data payload into the bronze layer via webhook ingestion. "
            "Step 1: call list_connectors to find or confirm the target connector. "
            "Step 2: if no connector exists, create one with create_connector first. "
            "Step 3: show the user exactly what data will be sent and to which table, "
            "then confirm. "
            "Step 4: call this tool with connector_id (preferred) or an explicit source name. "
            "The bronze table name is derived from the connector's linked entity name, "
            "or from the connector name if no entity is linked. "
            "After ingesting, call get_connector_runs to verify rows landed successfully."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "connector_id": {
                    "type": "string",
                    "description": (
                        "UUID of an existing webhook connector. "
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
        "name": "create_connector",
        "description": (
            "Register a new data connector (webhook receiver, batch file upload, or API pull). "
            "Choose connector_type based on how data will arrive:\n"
            "  - 'webhook': for real-time JSON events pushed via HTTP POST\n"
            "  - 'batch_csv': for periodic CSV file uploads (max 50 MB)\n"
            "  - 'batch_json': for periodic JSON file uploads (array or newline-delimited)\n"
            "  - 'api_pull': platform fetches JSON from a remote URL on demand"
            " (requires config.url)\n"
            "When creating a connector for an existing catalogue entity, pass entity_id so "
            "the entity's name becomes the canonical bronze table — ingest and preview will "
            "always refer to the same table. If no entity exists yet, create one with "
            "register_entity first (infer_schema → register_entity → create_connector). "
            "For api_pull connectors, call discover_api first to inspect the remote data. "
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
                        "Connector-specific config. For api_pull: "
                        '{"url": "https://api.example.com/data", '
                        '"headers": {"Authorization": "Bearer <token>"}}'
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
                "trigger_mode": {
                    "type": "string",
                    "enum": ["manual", "on_change"],
                    "description": (
                        "When to run: 'manual' (default, requires explicit execute) or "
                        "'on_change' (auto-runs when a watched entity receives new data). "
                        "Requires admin approval before auto-triggering."
                    ),
                },
                "watch_entities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Entity IDs to watch (UUIDs). When any of these entities receive new data "
                        "and trigger_mode='on_change', this transform runs automatically. "
                        "Required when trigger_mode='on_change'."
                    ),
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
                "trigger_mode": {
                    "type": "string",
                    "enum": ["manual", "on_change"],
                    "description": "Change the trigger mode (optional)",
                },
                "watch_entities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Updated list of entity IDs to watch (optional)",
                },
            },
            "required": ["transform_id"],
        },
    },
    # ── Memory ────────────────────────────────────────────────────────────────
    {
        "name": "save_memory",
        "description": (
            "Store a memory item for this tenant so it can be recalled in future sessions. "
            "Call this after solving a problem, learning a user preference, or discovering "
            "something important about the data. Good candidates: SQL patterns that worked, "
            "column quirks, user naming conventions, recurring workflows. "
            "Do NOT save trivial or session-specific information."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["routine", "solution", "preference", "context"],
                    "description": (
                        "routine — a recurring workflow the user wants automated; "
                        "solution — a working SQL pattern or fix; "
                        "preference — a naming/style choice the user has expressed; "
                        "context — a data quality finding or important fact about an entity"
                    ),
                },
                "summary": {
                    "type": "string",
                    "description": "One-sentence description (used for recall matching)",
                },
                "content": {
                    "description": (
                        "Structured detail: dict with relevant keys "
                        '(e.g. {"sql": "...", "entity": "orders"}) or plain string'
                    ),
                },
            },
            "required": ["category", "summary", "content"],
        },
    },
    {
        "name": "recall_memories",
        "description": (
            "Search stored memories for this tenant by keyword. "
            "Use this when you need to check if a pattern or preference was previously recorded, "
            "beyond what is auto-injected in the system prompt."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords to search for (entity names, column names, topic)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "forget_memory",
        "description": (
            "Delete a specific memory item by ID. "
            "Use when a memory is outdated, incorrect, or the user asks to forget something."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "UUID of the memory to delete",
                },
            },
            "required": ["memory_id"],
        },
    },
]
