"""LLM provider integration — agentic chat with tool use.

Phase 2 additions:
- Dynamic system prompt with live catalogue context (NL-to-SQL awareness)
- infer_schema and register_entity tool handlers
- PII masking applied to run_sql and preview_entity results
- Tenant-scoped SQL safety check
"""

from __future__ import annotations

import json
import re
from collections.abc import Generator
from typing import Any

from src.agent.inference import infer_from_csv, infer_from_json
from src.agent.pii import mask_rows
from src.agent.provider import build_provider_client
from src.agent.tools import TOOLS
from src.config import settings
from src.db.connection import get_conn

# Layers each role is allowed to query
_ROLE_ALLOWED_LAYERS: dict[str, set[str]] = {
    "owner": {"bronze", "silver", "gold"},
    "admin": {"bronze", "silver", "gold"},
    "engineer": {"bronze", "silver", "gold"},
    "analyst": {"silver", "gold"},
    "viewer": {"gold"},
}

_LAYER_PATTERN = re.compile(r"\b(bronze|silver|gold)\.\w+", re.IGNORECASE)

_OPENAI_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["input_schema"],
        },
    }
    for tool in TOOLS
]


def _sql_error_hint(err: str) -> str:
    """Return a DuckDB-specific hint based on common SQL error patterns."""
    e = err.lower()
    if "json_array_elements" in e or "json_each" in e:
        return (
            " Hint: json_array_elements and json_each are Postgres functions — "
            "not supported in DuckDB. Use: "
            "CROSS JOIN UNNEST(json_extract(payload, '$.array_field')::JSON[]) AS t(elem)"
        )
    if "lateral" in e and ("cross join" in e or "join" in e):
        return (
            " Hint: CROSS JOIN LATERAL is not supported in DuckDB. "
            "Use: CROSS JOIN UNNEST(json_extract(payload, '$.array_field')::JSON[]) AS t(elem)"
        )
    if "unnest" in e and ("json" in e or "cast" in e or "type" in e):
        return (
            " Hint: UNNEST requires an array type. Cast the JSON array first: "
            "UNNEST(json_extract(payload, '$.array_field')::JSON[]) AS t(elem). "
            "The ::JSON[] cast is required."
        )
    col_match = re.search(r'does not have a column named "([^"]+)"', err, re.IGNORECASE)
    if col_match:
        col = col_match.group(1)
        return (
            f' Hint: "{col}" is not a physical column. '
            f"For webhook/api_pull tables the field lives inside the `payload` JSON column — "
            f"use json_extract_string(payload, '$.{col}') for strings or "
            f"CAST(json_extract(payload, '$.{col}') AS DOUBLE/TIMESTAMP) for typed values. "
            "Call describe_entity to see physical_columns and payload_keys."
        )
    return ""


def _validate_sql_dry_run(sql: str, conn: Any) -> str | None:
    """Execute each SELECT block with LIMIT 1 to catch runtime errors before saving.

    Returns an error message string, or None if validation passes.
    EXPLAIN only catches parse/bind errors; running with LIMIT 1 also catches
    type mismatches, bad JSON casts, UNNEST failures, etc.
    """
    select_blocks: list[str] = []

    # CTAS: CREATE TABLE ... AS SELECT ...
    for m in re.finditer(r"(?i)\bAS\s+(SELECT\b.+?)(?=;|$)", sql, re.DOTALL):
        select_blocks.append(m.group(1).strip().rstrip(";"))

    # INSERT [OR REPLACE/IGNORE] INTO table SELECT ...
    for m in re.finditer(
        r"(?i)\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+\S+\s+(SELECT\b.+?)(?=;|$)",
        sql,
        re.DOTALL,
    ):
        select_blocks.append(m.group(1).strip().rstrip(";"))

    # Bare SELECT
    if not select_blocks and re.match(r"(?i)\s*SELECT\b", sql.strip()):
        select_blocks.append(sql.strip().rstrip(";"))

    for sel in select_blocks:
        try:
            conn.execute(f"SELECT * FROM ({sel}) AS _dry_run_q LIMIT 1")
        except Exception as exc:
            return str(exc)
    return None


def _check_sql_scope(sql: str, role: str) -> str | None:
    """Return an error message if SQL references a layer the role cannot access."""
    allowed = _ROLE_ALLOWED_LAYERS.get(role, {"gold"})
    for match in _LAYER_PATTERN.finditer(sql):
        layer = match.group(1).lower()
        if layer not in allowed:
            return (
                f"Access denied: your role ({role}) cannot query the {layer} layer. "
                f"You have access to: {', '.join(sorted(allowed))}."
            )
    return None


_BASE_SYSTEM_PROMPT = """\
You are Jonas, an AI assistant embedded in a multi-tenant data platform.
You help data engineers and analysts ingest, clean, and query their data.

## Your capabilities
- Inspect data payloads and infer schemas (infer_schema)
- Register new entities in the catalogue (register_entity)
- Browse the catalogue to understand available data (list_entities, describe_entity)
- Answer data questions with SQL (run_sql, preview_entity)
- Draft SQL transforms for the bronze→silver→gold pipeline (draft_transform)
- List and create data connectors (list_connectors, create_connector)
- Discover external APIs before connecting (discover_api)
- Ingest data directly into the bronze layer via webhook (ingest_webhook)
- Check import run history to diagnose failures (get_connector_runs)

## Connector types
- **webhook** — external systems POST JSON to `/api/v1/connectors/<id>/webhook`
- **batch_csv** / **batch_json** — users upload files via the dashboard or
  `POST /api/v1/connectors/<id>/batch`
- **api_pull** — the platform fetches JSON from a configured remote URL on demand;
  trigger manually with `POST /api/v1/connectors/<id>/trigger` (no body required).
  The connector's `config` must contain
  `{{"url": "https://...", "headers": {{"Authorization": "Bearer ..."}}}}`.

## Data import flow — follow these steps precisely

When a user wants to import data, guide them through this exact sequence:

### Step 1 — Discover existing connectors
Call `list_connectors`. If a suitable connector already exists, skip to Step 4.
Tell the user: "I found connector '<name>' (type: <connector_type>, id: <id>).
We can use this to land your data into bronze.<table_name>."

### Step 2 — (If no connector) Infer schema from sample data
For **api_pull** connectors: call `discover_api` first with the endpoint URL to fetch
a real sample. This gives you actual field names and types before setting anything up.
For **webhook/batch** connectors: ask the user to provide a sample record (JSON object)
or CSV header row.
Call `infer_schema` with the sample. Present the detected fields and PII flags.
Confirm: "I'll register this as entity '<name>' in the bronze layer with these fields: ..."

### Step 3 — Register entity + create connector
After user confirms, call `register_entity`, then `create_connector` linking to that entity.
For webhook connectors, tell the user the exact endpoint to POST to:
  POST /api/v1/connectors/<connector_id>/webhook
  Headers: Authorization: Bearer <token>
  Body: {{"data": <your_payload>}}
For batch (CSV/JSON) connectors, tell the user to upload via the dashboard or:
  POST /api/v1/connectors/<connector_id>/batch
  Headers: Authorization: Bearer <token>
  Body: multipart/form-data with field 'file' containing the CSV or JSON file

### Step 4 — Ingest the data
For webhook: call `ingest_webhook` with the connector_id and the user's data.
For batch: instruct the user to upload the file via the dashboard Connectors page
(click the Upload button on the connector card) or use the batch API endpoint above.
For api_pull: tell the user to click the Pull button on the connector card in the dashboard,
or call the trigger endpoint directly:
  POST /api/v1/connectors/<connector_id>/trigger
  Headers: Authorization: Bearer <token>
  (no request body needed)

### Step 5 — Verify the import
Call `get_connector_runs` to confirm rows landed. If there are failures, explain
the error_detail and suggest fixes.

### Step 6 — (Optional) Preview and transform
Call `preview_entity` to show the user their landed data.
If cleaning is needed, offer to `draft_transform` to promote to silver/gold.

## Silver transform rules
- Silver tables clean, type-cast, and deduplicate bronze data.
- **Always use the two-statement upsert pattern** (CREATE TABLE IF NOT EXISTS + INSERT OR REPLACE).
  This is the ONLY supported pattern for silver/gold transforms. Never use bare SELECT or CTAS.
- Never DROP or TRUNCATE silver tables. Never use CREATE TABLE AS SELECT (CTAS) for silver/gold.
- Every silver table must have a PRIMARY KEY column for deduplication.
- Always call `describe_entity` on the source first — use only physically existing columns.
- Call `list_transforms` before drafting — update an existing transform instead of creating
  a duplicate.
- **After `draft_transform` succeeds, always register the output table as a catalogue entity.**
  Call `register_entity` with the target layer (`silver` or `gold`), the output table name, and
  the inferred fields from the CREATE TABLE column list. Do this automatically — do not wait for
  the user to ask. Confirm to the user: "I've also registered `silver.orders` as a catalogue entity."

**Mandatory two-statement upsert pattern:**
```sql
CREATE TABLE IF NOT EXISTS silver.orders (
    order_id VARCHAR PRIMARY KEY,
    customer_id VARCHAR,
    amount DOUBLE,
    status VARCHAR,
    ordered_at TIMESTAMP
);

INSERT OR REPLACE INTO silver.orders
SELECT
    json_extract_string(payload, '$.order_id') AS order_id,
    json_extract_string(payload, '$.customer_id') AS customer_id,
    CAST(json_extract(payload, '$.total') AS DOUBLE) AS amount,
    json_extract_string(payload, '$.status') AS status,
    CAST(json_extract(payload, '$.created_at') AS TIMESTAMP) AS ordered_at
FROM bronze.orders
WHERE json_extract_string(payload, '$.order_id') IS NOT NULL;
```

- Statement 1: `CREATE TABLE IF NOT EXISTS` with explicit column types and PRIMARY KEY.
  This is idempotent — safe to run repeatedly, creates the table only on first run.
- Statement 2: `INSERT OR REPLACE INTO` with the SELECT. This upserts all matching rows.
- Both statements must be separated by a `;` and included together in `transform_sql`.
- The SELECT columns must exactly match the CREATE TABLE column names and order.

## Rules
- Only generate DuckDB-compatible SQL. Reference tables as `layer.entity_name`
  (e.g. `bronze.orders`).
- Never approve your own transform drafts — always tell the user it needs admin approval.
- When writing transforms, produce CREATE TABLE AS SELECT statements targeting
  the correct layer schema.
- PII fields are automatically masked in query results — you don't need to handle this yourself.
- Always confirm with the user before registering an entity, drafting a transform,
  or creating an integration.
- When giving API endpoint instructions, always show the exact URL, required headers,
  and a concrete example body — never make the user guess.
- Be concise. Lead with the answer or action, then explain if needed.

## Physical storage formats
Bronze tables have two possible physical layouts depending on how data was ingested:
1. **Webhook / api_pull format** — columns:
   `id, tenant_id, ingested_at, source, payload JSON, metadata JSON`.
   Field values live inside `payload`. Access with: `json_extract(payload, '$.field_name')` or
   `payload->>'field_name'` (DuckDB shorthand).
   Example: `SELECT json_extract(payload, '$.user_id') AS user_id FROM bronze.orders`
2. **Batch CSV format** — individual columns per field (e.g. `user_id, amount, status`).
   Use column names directly.

The system prompt shows "PHYSICAL STORAGE: webhook/api_pull format" or "Physical columns" for each
entity. **Always read this before writing SQL.** Never reference a column name that isn't in the
physical columns list. For webhook tables, always use json_extract for field access.

## SQL rules — follow every time before writing a transform or query
1. **Call `describe_entity` for every source table** before writing SQL.
   Read `storage_format`, `physical_columns`, `payload_keys`, and `payload_array_fields` in the response.
2. **Webhook/api_pull tables** (`storage_format: "webhook"`):
   - Fields live inside `payload` JSON — NEVER use bare field names as columns.
   - Strings: `json_extract_string(payload, '$.field_name')`
   - Numbers: `CAST(json_extract(payload, '$.field_name') AS DOUBLE)`
   - Timestamps: `CAST(json_extract(payload, '$.field_name') AS TIMESTAMP)`
   - Joins: `json_extract_string(a.payload, '$.id') = b.some_column`
3. **CSV/flat tables** (`storage_format: "csv"`):
   - All columns in `physical_columns` are directly usable.
   - All values are VARCHAR — CAST for arithmetic or date comparisons.
4. **Cross-format joins** are common and require mixing both patterns:
   ```sql
   SELECT
     json_extract_string(o.payload, '$.order_id') AS order_id,
     c.contact_id
   FROM bronze.orders o  -- webhook format
   JOIN bronze.contacts c  -- csv format
     ON json_extract_string(o.payload, '$.customer_email') = c.email
   ```
5. The `draft_transform` tool validates SQL by executing each SELECT with LIMIT 1
   before saving. If it returns an error, fix the SQL and retry — do not save broken transforms.
6. **After debugging SQL interactively with `run_sql`**: the working SQL exists only in
   the conversation, not in the stored transform. You MUST call `update_transform` with
   the verified SQL before telling the user the transform is ready for approval.
   Skipping this means the stored transform still has the old broken SQL and will fail on execution.
7. **When a transform execution fails**: call `describe_entity` on each source table,
   check `physical_columns` and `payload_keys`, fix the SQL, call `update_transform`,
   then ask the admin to re-approve. Do not ask the admin to retry the same SQL.

## JSON array unnesting (DuckDB syntax)

When a payload field contains a JSON array, `describe_entity` returns `payload_array_fields`
mapping each array key to a sample of its sub-keys.

**DuckDB-correct pattern — use CROSS JOIN UNNEST with ::JSON[] cast:**
```sql
-- Expand products[] from an orders payload: one output row per product per order
SELECT
    json_extract_string(o.payload, '$.order_id') AS order_id,
    json_extract_string(p.elem, '$.productId')   AS product_id,
    CAST(json_extract(p.elem, '$.quantity') AS INTEGER) AS qty
FROM bronze.orders o
CROSS JOIN UNNEST(json_extract(o.payload, '$.products')::JSON[]) AS p(elem);
```

**Rules:**
- Use `CROSS JOIN UNNEST(json_extract(payload, '$.array_field')::JSON[]) AS t(elem)`
- The `::JSON[]` cast is REQUIRED — UNNEST needs an array type, not a raw JSON value
- Access sub-fields from the element: `json_extract_string(t.elem, '$.sub_field')`
- **NOT supported in DuckDB**: `CROSS JOIN LATERAL`, `json_array_elements`, `json_each`
  These are Postgres functions that do not exist in DuckDB. If you use them, the SQL will fail.
- If the payload field might be NULL or not always an array, add a WHERE guard:
  `WHERE json_extract(payload, '$.array_field') IS NOT NULL`

## Relationship rules (read carefully)
- The system prompt always includes the current state of entities, connectors, and transforms.
  Read it before taking any action — do not create duplicates.
- **Connectors must link to an entity**: always pass `entity_id` when creating a connector.
  The entity determines the bronze table name. If no entity exists yet, create one first.
- **Transforms must reference real tables**: before writing SQL, confirm the source table
  (`source_layer.entity_name`) exists in the catalogue. Never reference a table that isn't listed.
- **Before draft_transform**: call `list_transforms` — if a transform with the same name or
  purpose exists, call `update_transform` instead. Creating a duplicate will fail.
- **Before create_connector**: check the connectors listed above — if one already feeds the
  same entity, tell the user and ask whether they want to create another or reuse the existing one.
- **Medallion flow**: bronze = raw ingested data. silver = cleaned/typed.
  gold = aggregated/business.
  Transforms always go bronze→silver or silver→gold, never backwards or skipping layers.

{catalogue_context}
"""


def _build_system_prompt(tenant_id: str, role: str) -> str:
    from src.catalogue.service import build_catalogue_context

    try:
        ctx = build_catalogue_context(tenant_id, role)
    except Exception:
        ctx = "(catalogue unavailable)"
    return _BASE_SYSTEM_PROMPT.format(catalogue_context=ctx)


def _pii_fields_for_entity(entity_id: str) -> set[str]:
    """Return the set of PII field names for an entity."""
    from src.catalogue.service import get_entity_fields

    fields = get_entity_fields(entity_id)
    return {f["name"] for f in fields if f.get("is_pii")}


def _has_pii_access(role: str) -> bool:
    """Admins and owners can see unmasked PII. Everyone else gets masked output."""
    return role in ("owner", "admin")


def _run_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    tenant_id: str,
    role: str,
    created_by: str,
) -> str:
    """Dispatch a tool call and return the result as a JSON string."""
    conn = get_conn()

    # ── list_entities ────────────────────────────────────────────────────────
    if tool_name == "list_entities":
        from src.catalogue.service import get_accessible_entities

        entities = get_accessible_entities(tenant_id, role)
        layer = tool_input.get("layer")
        if layer:
            entities = [e for e in entities if e.get("layer") == layer]
        # Trim fields list to just names to keep response compact
        summary = [
            {
                "id": e["id"],
                "name": e["name"],
                "layer": e.get("layer"),
                "description": e.get("description", ""),
                "field_count": len(e.get("fields", [])),
            }
            for e in entities
        ]
        return json.dumps(summary)

    # ── describe_entity ──────────────────────────────────────────────────────
    if tool_name == "describe_entity":
        from src.catalogue.service import get_entity, get_entity_fields

        entity = get_entity(tool_input["entity_id"], tenant_id)
        if not entity:
            return json.dumps({"error": "Entity not found"})
        entity["fields"] = get_entity_fields(entity["id"])

        # Add physical DuckDB schema — this is the source of truth for SQL
        layer = entity.get("layer", "bronze")
        name = entity.get("name", "")
        try:
            phys_rows = conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
                [layer, name],
            ).fetchall()
            phys_cols = [r[0] for r in phys_rows]
            # Detect storage format from physical column signatures:
            # - webhook: created by land_webhook/land_api_pull/land_batch_json
            #   has exactly: id, tenant_id, ingested_at, source, payload, metadata
            # - csv: created by land_batch_csv
            #   has: _id, _tenant_id, _ingested_at, ...flat VARCHAR cols...
            # - flat: silver/gold table created by a transform (typed structured cols)
            _WEBHOOK_SIGNATURE = {
                "id",
                "tenant_id",
                "ingested_at",
                "source",
                "payload",
                "metadata",
            }
            _CSV_SIGNATURE = {"_id", "_tenant_id", "_ingested_at"}
            phys_set = set(phys_cols)
            is_webhook = _WEBHOOK_SIGNATURE.issubset(phys_set)
            is_csv = _CSV_SIGNATURE.issubset(phys_set) and "payload" not in phys_set

            entity["physical_columns"] = phys_cols
            if is_webhook:
                entity["storage_format"] = "webhook"
                entity["sql_hint"] = (
                    "WEBHOOK FORMAT: logical fields are inside the `payload` JSON column. "
                    "Use json_extract_string(payload, '$.field') for strings, "
                    "CAST(json_extract(payload, '$.field') AS DOUBLE/TIMESTAMP/etc) for typed values. "
                    "Never reference catalogue field names as direct SQL columns — they do not exist."
                )
                # Surface the actual JSON keys inside payload from a real row,
                # and expose nested array structure for UNNEST guidance.
                try:
                    row = conn.execute(
                        f"SELECT payload FROM {layer}.{name} LIMIT 1"  # noqa: S608
                    ).fetchone()
                    if row and row[0]:
                        sample = (
                            json.loads(row[0]) if isinstance(row[0], str) else row[0]
                        )
                        if isinstance(sample, dict):
                            entity["payload_keys"] = list(sample.keys())[:20]
                            # Detect array-of-objects fields and expose their sub-keys
                            array_fields: dict[str, list[str]] = {}
                            for k, v in sample.items():
                                if isinstance(v, list) and v and isinstance(v[0], dict):
                                    array_fields[k] = list(v[0].keys())[:10]
                            if array_fields:
                                entity["payload_array_fields"] = array_fields
                                entity["unnest_hint"] = (
                                    "DuckDB JSON array unnesting — required syntax: "
                                    "CROSS JOIN UNNEST(json_extract(payload, '$.array_field')::JSON[]) AS t(elem). "
                                    "Access sub-fields with json_extract_string(t.elem, '$.sub_key'). "
                                    "NOT supported: CROSS JOIN LATERAL, json_array_elements, json_each."
                                )
                        elif (
                            isinstance(sample, list)
                            and sample
                            and isinstance(sample[0], dict)
                        ):
                            entity["payload_keys"] = list(sample[0].keys())[:20]
                except Exception:
                    pass
            elif is_csv:
                entity["storage_format"] = "csv"
                entity["sql_hint"] = (
                    "CSV FORMAT: use physical_columns directly (strip the leading _ from _id/_tenant_id/_ingested_at). "
                    "All user data columns are VARCHAR — CAST as needed for arithmetic or timestamp comparisons."
                )
            else:
                entity["storage_format"] = "flat"
                entity["sql_hint"] = (
                    "FLAT FORMAT: typed structured table (created by a transform). "
                    "Use physical_columns directly — columns already have correct types, no JSON extraction needed."
                )
        except Exception:
            pass

        return json.dumps(entity, default=str)

    # ── infer_schema ─────────────────────────────────────────────────────────
    if tool_name == "infer_schema":
        sample = tool_input.get("sample")
        fmt = tool_input.get("format", "json")
        try:
            if fmt == "csv" and isinstance(sample, list):
                headers = list(sample[0].keys()) if sample else []
                fields = infer_from_csv(headers, sample)
            else:
                fields = infer_from_json(sample)  # type: ignore[arg-type]
            return json.dumps(
                {
                    "field_count": len(fields),
                    "fields": fields,
                    "pii_fields": [f["name"] for f in fields if f.get("is_pii")],
                }
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # ── register_entity ──────────────────────────────────────────────────────
    if tool_name == "register_entity":
        from src.catalogue.service import create_entity, create_fields_bulk

        if not tool_input.get("name"):
            return json.dumps({"error": "register_entity requires 'name'"})
        layer = tool_input.get("layer", "bronze")
        if layer not in ("bronze", "silver", "gold"):
            layer = "bronze"
        entity_data = {
            "name": tool_input["name"],
            "layer": layer,
            "description": tool_input.get("description", ""),
            "tags": [tool_input["namespace"]] if tool_input.get("namespace") else [],
        }
        entity = create_entity(entity_data, tenant_id)
        fields = create_fields_bulk(
            entity["id"], tool_input.get("fields", []), created_by
        )
        entity["fields"] = fields
        return json.dumps(entity, default=str)

    # ── run_sql ──────────────────────────────────────────────────────────────
    if tool_name == "run_sql":
        sql = tool_input.get("sql", "").strip()
        limit = min(int(tool_input.get("limit", 100)), 1000)

        if not sql.upper().startswith("SELECT"):
            return json.dumps({"error": "Only SELECT statements are permitted."})

        scope_error = _check_sql_scope(sql, role)
        if scope_error:
            return json.dumps({"error": scope_error})

        try:
            rows_raw = conn.execute(f"{sql} LIMIT {limit}").fetchall()
            cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
            rows = [dict(zip(cols, row)) for row in rows_raw]

            # Mask PII if user lacks access
            if not _has_pii_access(role):
                # Detect PII columns by name heuristic (conservative)
                from src.agent.inference import _is_pii  # type: ignore[attr-defined]
                from src.agent.pii import mask_rows as _mask

                pii_cols = {c for c in cols if _is_pii(c)}
                rows = _mask(rows, pii_cols, False)

            return json.dumps({"rows": rows, "count": len(rows)}, default=str)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # ── preview_entity ───────────────────────────────────────────────────────
    if tool_name == "preview_entity":
        from src.catalogue.service import get_entity, get_entity_fields

        entity_id = tool_input["entity_id"]
        limit = min(int(tool_input.get("limit", 10)), 100)
        entity = get_entity(entity_id, tenant_id)
        if not entity:
            return json.dumps({"error": "Entity not found"})

        allowed_layers = _ROLE_ALLOWED_LAYERS.get(role, {"gold"})
        if entity.get("layer") not in allowed_layers:
            return json.dumps(
                {
                    "error": (
                        f"Access denied: your role ({role}) cannot access the "
                        f"{entity['layer']} layer."
                    )
                }
            )

        table_ref = f"{entity['layer']}.{entity['name']}"
        try:
            rows_raw = conn.execute(
                f"SELECT * FROM {table_ref} LIMIT {limit}"  # noqa: S608
            ).fetchall()
            cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
            rows = [dict(zip(cols, row)) for row in rows_raw]

            pii_field_names = _pii_fields_for_entity(entity_id)
            rows = mask_rows(rows, pii_field_names, _has_pii_access(role))

            return json.dumps(
                {"entity": table_ref, "rows": rows, "count": len(rows)}, default=str
            )
        except Exception as exc:
            return json.dumps({"error": str(exc), "entity": table_ref})

    # ── ingest_webhook ───────────────────────────────────────────────────────
    if tool_name == "ingest_webhook":
        from src.auth.permissions import Action, Resource, can
        from src.integrations.ingest import land_webhook
        from src.integrations.service import get_integration

        if not can({"role": role}, Resource.INTEGRATION, Action.WRITE):
            return json.dumps(
                {"error": f"Access denied: role '{role}' cannot ingest data."}
            )

        # Resolve source: prefer connector_id → entity.name (if linked) → connector.name
        # Accept both connector_id (new) and integration_id (legacy) for backward compat
        integration_id = tool_input.get("connector_id") or tool_input.get(
            "integration_id"
        )
        if integration_id:
            integration = get_integration(integration_id, tenant_id)
            if not integration:
                return json.dumps({"error": f"Connector '{integration_id}' not found."})
            if integration.get("connector_type") != "webhook":
                return json.dumps(
                    {
                        "error": (
                            f"Connector '{integration['name']}' has connector_type "
                            f"'{integration['connector_type']}', not 'webhook'."
                        )
                    }
                )
            entity_id = integration.get("target_entity_id")
            if entity_id:
                from src.catalogue.service import get_entity

                entity = get_entity(str(entity_id), tenant_id)
                if not entity:
                    return json.dumps(
                        {"error": f"Linked catalogue entity '{entity_id}' not found."}
                    )
                source = str(entity["name"])
            else:
                source = str(integration["name"])
        else:
            source = tool_input.get("source", "")

        if not source:
            return json.dumps(
                {
                    "error": "Provide either integration_id or source to identify the target table."
                }
            )

        data = tool_input.get("data", {})
        metadata = tool_input.get("metadata", {})
        result = land_webhook(source, data, metadata, tenant_id)
        return json.dumps(result)

    # ── list_connectors ──────────────────────────────────────────────────────
    if tool_name == "list_connectors":
        from src.integrations.service import list_integrations

        connectors = list_integrations(tenant_id)
        summary = [
            {
                "id": i["id"],
                "name": i["name"],
                "connector_type": i.get("connector_type"),
                "status": i.get("status"),
                "description": i.get("description", ""),
                "entity_id": i.get("target_entity_id"),
                "webhook_endpoint": f"/api/v1/connectors/{i['id']}/webhook"
                if i.get("connector_type") == "webhook"
                else None,
                "batch_endpoint": f"/api/v1/connectors/{i['id']}/batch"
                if i.get("connector_type") in ("batch_csv", "batch_json")
                else None,
                "trigger_endpoint": f"/api/v1/connectors/{i['id']}/trigger"
                if i.get("connector_type") == "api_pull"
                else None,
            }
            for i in connectors
        ]
        return json.dumps(summary)

    # ── get_connector_runs ───────────────────────────────────────────────────
    if tool_name == "get_connector_runs":
        from src.integrations.service import list_runs

        connector_id = tool_input.get("connector_id", "")
        if not connector_id:
            return json.dumps({"error": "connector_id is required."})
        runs = list_runs(connector_id, tenant_id, limit=20)
        return json.dumps(runs, default=str)

    # ── discover_api ─────────────────────────────────────────────────────────
    if tool_name == "discover_api":
        import ipaddress
        import socket
        import urllib.parse

        import httpx

        url = tool_input.get("url", "").strip()
        if not url:
            return json.dumps({"error": "url is required"})

        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return json.dumps({"error": "Only http/https URLs are supported"})

        # SSRF guard: block private/internal addresses
        hostname = parsed.hostname or ""
        try:
            ip_str = socket.gethostbyname(hostname)
            addr = ipaddress.ip_address(ip_str)
            if (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_reserved
            ):
                return json.dumps(
                    {
                        "error": "Access to private/internal/loopback addresses is not permitted."
                    }
                )
        except socket.gaierror:
            return json.dumps({"error": f"Could not resolve hostname: {hostname!r}"})
        except ValueError:
            pass  # IPv6 etc — proceed optimistically

        method = tool_input.get("method", "GET").upper()
        headers: dict[str, str] = tool_input.get("headers") or {}
        body = tool_input.get("body")
        json_path: str = tool_input.get("json_path") or ""

        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                if method == "GET":
                    response = client.get(url, headers=headers)
                elif method == "POST":
                    response = client.post(url, headers=headers, json=body)
                elif method == "PUT":
                    response = client.put(url, headers=headers, json=body)
                else:
                    return json.dumps({"error": f"Unsupported method: {method}"})

                response.raise_for_status()
                data = response.json()

            # Extract records via dot-notation json_path
            records: object = data
            if json_path:
                for part in json_path.lstrip("$.").split("."):
                    if isinstance(records, dict):
                        records = records.get(part, records)

            if isinstance(records, dict):
                records = [records]

            total = len(records) if isinstance(records, list) else 0
            sample = records[:5] if isinstance(records, list) else records

            return json.dumps(
                {
                    "status_code": response.status_code,
                    "total_records": total,
                    "sample_records": sample,
                },
                default=str,
            )
        except httpx.HTTPStatusError as exc:
            return json.dumps(
                {"error": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"}
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # ── create_connector ─────────────────────────────────────────────────────
    if tool_name == "create_connector":
        from src.auth.permissions import Action, Resource, can
        from src.integrations.service import create_integration

        if not can({"role": role}, Resource.INTEGRATION, Action.WRITE):
            return json.dumps(
                {"error": f"Access denied: role '{role}' cannot create connectors."}
            )
        result = create_integration(tool_input, tenant_id)
        return json.dumps(result, default=str)

    # ── list_transforms ──────────────────────────────────────────────────────
    if tool_name == "list_transforms":
        from src.transforms.service import list_transforms

        transforms = list_transforms(tenant_id)
        summary = [
            {
                "id": t["id"],
                "name": t["name"],
                "description": t.get("description", ""),
                "source_layer": t.get("source_layer"),
                "target_layer": t.get("target_layer"),
                "status": t.get("status"),
                "sql_preview": (t.get("transform_sql") or "")[:120],
            }
            for t in transforms
        ]
        return json.dumps(summary)

    # ── draft_transform ──────────────────────────────────────────────────────
    if tool_name == "draft_transform":
        from src.transforms.service import create_transform

        sql = (tool_input.get("sql") or tool_input.get("transform_sql") or "").strip()
        if sql:
            # Dry-run: execute each SELECT block with LIMIT 1 to catch runtime errors
            # (type mismatches, UNNEST failures, bad JSON casts) that EXPLAIN misses.
            err = _validate_sql_dry_run(sql, conn)
            if err is not None:
                hint = _sql_error_hint(err)
                return json.dumps(
                    {
                        "error": (f"SQL validation failed before saving: {err}.{hint}"),
                        "sql": sql,
                    }
                )

        result = create_transform(tool_input, tenant_id, created_by=created_by)
        return json.dumps(result, default=str)

    # ── update_transform ─────────────────────────────────────────────────────
    if tool_name == "update_transform":
        from src.transforms.service import update_transform

        transform_id = tool_input.pop("transform_id", None)
        if not transform_id:
            return json.dumps({"error": "transform_id is required."})

        # Validate new SQL before saving, same as draft_transform
        new_sql = (
            tool_input.get("transform_sql") or tool_input.get("sql") or ""
        ).strip()
        if new_sql:
            err = _validate_sql_dry_run(new_sql, conn)
            if err is not None:
                hint = _sql_error_hint(err)
                return json.dumps(
                    {
                        "error": f"SQL validation failed — transform not updated: {err}.{hint}",
                        "sql": new_sql,
                    }
                )

        result = update_transform(transform_id, tool_input, tenant_id)
        if not result:
            return json.dumps({"error": f"Transform '{transform_id}' not found."})
        return json.dumps(result, default=str)

    return json.dumps({"error": f"Unknown tool: {tool_name}"})


def chat(
    messages: list[dict[str, Any]],
    tenant_id: str,
    role: str = "viewer",
    user_id: str = "unknown",
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Run an agentic conversation turn with tool use.

    Builds a live system prompt from the catalogue, then loops until
    the model stops calling tools.
    """
    provider_client = build_provider_client()
    system_prompt = _build_system_prompt(tenant_id, role)
    conversation: list[dict[str, Any]] = [
        {
            "role": str(msg.get("role", "user")),
            "content": str(msg.get("content", "")),
        }
        for msg in messages
    ]

    while True:
        response = provider_client.client.chat.completions.create(
            model=settings.llm_model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system_prompt}, *conversation],
            tools=_OPENAI_TOOLS,
            tool_choice="auto",
            **provider_client.request_overrides,
        )

        if not response.choices:
            return {"role": "assistant", "content": "No response from the model."}

        assistant_message = response.choices[0].message
        tool_calls = assistant_message.tool_calls or []

        if not tool_calls:
            return {"role": "assistant", "content": assistant_message.content or ""}

        assistant_turn: dict[str, Any] = {
            "role": "assistant",
            "content": assistant_message.content or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in tool_calls
            ],
        }
        conversation.append(assistant_turn)

        for call in tool_calls:
            try:
                tool_input = json.loads(call.function.arguments or "{}")
                if not isinstance(tool_input, dict):
                    raise ValueError("Tool arguments must be a JSON object.")
            except Exception as exc:
                result = json.dumps({"error": f"Invalid tool arguments: {exc}"})
            else:
                result = _run_tool(
                    call.function.name,
                    tool_input,
                    tenant_id,
                    role,
                    user_id,
                )

            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result,
                }
            )


def stream_chat(
    messages: list[dict[str, Any]],
    tenant_id: str,
    role: str = "viewer",
    user_id: str = "unknown",
    max_tokens: int = 4096,
) -> Generator[str, None, None]:
    """Stream an agentic conversation turn as SSE-formatted events.

    Emits three event types:
    - ``{"type": "tool", "name": "<tool_name>"}`` — tool being invoked
    - ``{"type": "delta", "text": "<token>"}`` — text token from model
    - ``{"type": "done"}`` — conversation turn complete
    """
    provider_client = build_provider_client()
    system_prompt = _build_system_prompt(tenant_id, role)
    conversation: list[dict[str, Any]] = [
        {
            "role": str(msg.get("role", "user")),
            "content": str(msg.get("content", "")),
        }
        for msg in messages
    ]

    while True:
        stream = provider_client.client.chat.completions.create(
            model=settings.llm_model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system_prompt}, *conversation],
            tools=_OPENAI_TOOLS,
            tool_choice="auto",
            stream=True,
            **provider_client.request_overrides,
        )

        assistant_text_parts: list[str] = []
        partial_tool_calls: dict[int, dict[str, Any]] = {}

        for chunk in stream:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            if delta.content:
                assistant_text_parts.append(delta.content)
                yield f"data: {json.dumps({'type': 'delta', 'text': delta.content})}\n\n"

            if not delta.tool_calls:
                continue

            for tool_delta in delta.tool_calls:
                index = tool_delta.index if tool_delta.index is not None else 0
                partial = partial_tool_calls.setdefault(
                    index,
                    {"id": "", "name": "", "arguments_parts": []},
                )

                if tool_delta.id:
                    partial["id"] = tool_delta.id

                if tool_delta.function:
                    if tool_delta.function.name:
                        partial["name"] = tool_delta.function.name
                    if tool_delta.function.arguments:
                        partial["arguments_parts"].append(tool_delta.function.arguments)

        if not partial_tool_calls:
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        ordered = [partial_tool_calls[i] for i in sorted(partial_tool_calls)]
        assistant_tool_calls: list[dict[str, Any]] = []
        for idx, partial in enumerate(ordered):
            call_id = partial["id"] or f"tool_call_{idx}"
            call_name = partial["name"] or ""
            call_args = "".join(partial["arguments_parts"]) or "{}"
            assistant_tool_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": call_name,
                        "arguments": call_args,
                    },
                }
            )

        conversation.append(
            {
                "role": "assistant",
                "content": "".join(assistant_text_parts),
                "tool_calls": assistant_tool_calls,
            }
        )

        for call in assistant_tool_calls:
            tool_name = str(call["function"]["name"])
            yield f"data: {json.dumps({'type': 'tool', 'name': tool_name})}\n\n"

            try:
                tool_input = json.loads(str(call["function"]["arguments"]) or "{}")
                if not isinstance(tool_input, dict):
                    raise ValueError("Tool arguments must be a JSON object.")
            except Exception as exc:
                result = json.dumps({"error": f"Invalid tool arguments: {exc}"})
            else:
                result = _run_tool(
                    tool_name,
                    tool_input,
                    tenant_id,
                    role,
                    user_id,
                )

            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": str(call["id"]),
                    "content": result,
                }
            )
