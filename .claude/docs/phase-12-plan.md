# Phase 12 — Python Execution Data Pipeline

## Goal

Replace the multi-step manual import dance (discover → register → create connector → ingest → draft transform → approve → execute) with a streamlined pipeline where:

1. **API pull connectors handle pagination** — fetch ALL pages automatically
2. **All ingestion uses uniform payload format** — batch_csv wraps rows as JSON payloads for traceability
3. **A new `smart_import` server-side tool** — deterministically chains the full pipeline in one shot
4. **Auto-generated bronze→silver flattening transforms** — with `on_change` trigger mode

---

## Work Stream 1: Paginated API Pull

### Problem
`land_api_pull()` makes a single HTTP GET. Real APIs return paginated data — offset-based, cursor-based, Link-header, or next-URL patterns.

### Design
Add a `pagination` key to the connector `config` dict. The ingest layer loops until exhausted.

**Config schema** (all fields optional — no pagination by default):
```json
{
  "url": "https://api.example.com/orders",
  "headers": {"Authorization": "Bearer ..."},
  "json_path": "data.items",
  "pagination": {
    "strategy": "offset|cursor|link_header|next_url",
    "page_size": 100,
    "max_pages": 50,
    "offset_param": "offset",
    "limit_param": "limit",
    "cursor_param": "cursor",
    "cursor_path": "meta.next_cursor",
    "next_url_path": "next"
  }
}
```

**Strategies:**
- `offset` — increment `offset_param` by `page_size` each page; stop when response records < page_size or 0
- `cursor` — read `cursor_path` from response; send as `cursor_param` query param; stop when cursor is null/empty
- `link_header` — parse `Link: <url>; rel="next"` header; stop when no `rel="next"`
- `next_url` — read `next_url_path` from response body; stop when null/empty

**Safety caps:**
- `max_pages` default 100, hard cap 500
- `max_records` hard cap 50,000 per pull
- Per-page SSRF check on `next_url` and `link_header` URLs (prevent redirect to internal)
- 30s timeout per page request

### Files to change

| File | Change |
|------|--------|
| `services/api/src/integrations/ingest.py` | New `land_api_pull_paginated()` replacing current `land_api_pull()`; pagination loop with strategy dispatch |
| `services/api/src/agent/handlers/connectors.py` | `trigger_connector` passes full config (including `json_path`, `pagination`) to ingest |
| `services/api/src/integrations/router.py` | `POST /{id}/trigger` endpoint passes pagination config |
| `services/api/src/agent/tools.py` | Update `create_connector` config description to document pagination options |
| `services/api/src/agent/prompt.py` | Document pagination config in connector types section |

### Implementation detail

```python
# In ingest.py — new helper
def _resolve_json_path(data: Any, path: str) -> Any:
    """Navigate dot-notation path into a dict. e.g. 'data.items' → data['data']['items']"""
    for part in path.split("."):
        if isinstance(data, dict):
            data = data.get(part)
        else:
            return None
    return data

def land_api_pull(
    url: str,
    headers: dict[str, str],
    source: str,
    tenant_id: str,
    integration_id: str | None = None,
    json_path: str = "",
    pagination: dict | None = None,
) -> dict[str, Any]:
    """Fetch JSON from a remote URL with optional pagination and land into bronze."""
    # ... pagination loop dispatches by strategy
    # Each page: fetch → extract records via json_path → land_webhook each record
    # Accumulate totals across pages
    # Fire trigger once at end
```

### Tests
- `test_paginated_api_pull_offset` — mock httpx responses with 3 pages of offset data
- `test_paginated_api_pull_cursor` — mock cursor-based pagination
- `test_paginated_api_pull_max_pages_cap` — ensure max_pages respected
- `test_paginated_api_pull_no_pagination` — backward compat, single fetch
- `test_paginated_ssrf_next_url` — next_url pointing to internal IP blocked

---

## Work Stream 2: Uniform Payload Format (batch_csv → webhook format)

### Problem
`land_batch_csv()` creates flat-column tables (`_id, _tenant_id, _ingested_at, col1, col2, ...`). This diverges from webhook format and means:
- Different SQL patterns needed for CSV vs webhook sources
- No payload-level traceability for CSV rows
- `describe_entity` must handle two storage formats
- Agent prompt needs two sets of SQL examples

### Design
Rewrite `land_batch_csv()` to wrap each CSV row as a JSON payload and delegate to `land_webhook()`, exactly like `land_batch_json()` already does.

Each CSV row becomes:
```json
{
  "id": "<uuid>",
  "tenant_id": "...",
  "ingested_at": "...",
  "source": "...",
  "payload": {"col1": "val1", "col2": "val2", ...},
  "metadata": {"format": "csv", "row_number": 42}
}
```

### Impact
- **Simplifies the entire SQL layer** — one extraction pattern everywhere (json_extract)
- **Simplifies agent prompt** — remove all "CSV format" branches
- **Simplifies describe_entity** — remove CSV storage format detection
- **Preserves original values** — payload is the verbatim CSV row dict
- **Row traceability** — `metadata.row_number` tracks original position

### Files to change

| File | Change |
|------|--------|
| `services/api/src/integrations/ingest.py` | Rewrite `land_batch_csv()` to parse CSV → list of dicts → delegate to `land_webhook()` per record (same pattern as `land_batch_json`) |
| `services/api/src/agent/prompt.py` | Remove "Batch CSV format" section; simplify to single webhook format everywhere |
| `services/api/src/agent/handlers/catalogue.py` | Simplify `describe_entity` — remove CSV detection branch (everything is webhook format now) |
| `services/api/src/agent/skills/json_patterns.py` | Remove "Cross-format join" pattern (#4); all joins use json_extract |

### Tests
- `test_batch_csv_lands_as_payload` — verify CSV rows become payload JSON
- `test_batch_csv_preserves_row_number` — metadata.row_number present
- `test_batch_csv_backward_compat_count` — same rows_received/rows_landed semantics

---

## Work Stream 3: Smart Import Tool

### Problem
The 6-step import flow requires the LLM to correctly chain 5-6 tool calls. It often drops steps, creates entities without connectors, or forgets to set up transforms.

### Design
A new **server-side composite tool** `smart_import` that deterministically executes the full pipeline:

1. Discover API (if url provided) or accept inline sample data
2. Extract records via `json_path`
3. Infer schema from sample records
4. Register bronze entity
5. Create connector (with pagination config for api_pull)
6. Ingest initial data (all pages for api_pull)
7. Generate bronze→silver flattening transform SQL
8. Register silver entity
9. Set transform to `on_change` watching the bronze entity
10. Return complete summary

**Tool definition:**
```python
{
    "name": "smart_import",
    "description": "End-to-end data import: discovers, registers, ingests, and creates a flattening transform — all in one step.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Entity name (snake_case, e.g. 'orders')"},
            "description": {"type": "string", "description": "What this data represents"},
            "source_type": {
                "type": "string",
                "enum": ["api_pull", "webhook", "sample_json"],
                "description": "How data arrives"
            },
            "url": {"type": "string", "description": "API URL (required for api_pull)"},
            "method": {"type": "string", "enum": ["GET", "POST"], "default": "GET"},
            "headers": {"type": "object", "description": "HTTP headers for api_pull"},
            "json_path": {"type": "string", "description": "Dot-path to records array in response"},
            "pagination": {
                "type": "object",
                "description": "Pagination config (strategy, page_size, max_pages, etc.)"
            },
            "sample_data": {"description": "Inline sample data (for webhook/sample_json)"},
            "namespace": {"type": "string", "description": "Logical grouping"},
            "collection": {"type": "string", "description": "Collection tag"},
            "primary_key_field": {
                "type": "string",
                "description": "Field name to use as primary key in silver table (auto-detected if not specified)"
            },
            "skip_transform": {
                "type": "boolean",
                "default": false,
                "description": "If true, skip creating the silver transform"
            }
        },
        "required": ["name", "source_type"]
    }
}
```

### Handler logic (new file: `services/api/src/agent/handlers/smart_import.py`)

```python
def handle_smart_import(tool_input, *, tenant_id, role, created_by) -> str:
    """Deterministic pipeline: discover → infer → register → connect → ingest → transform."""

    steps = []  # Track what was done for the summary

    # 1. Get sample data
    if source_type == "api_pull":
        # Fetch first page from URL (SSRF-checked)
        # Extract records via json_path
        sample = records[:5]
    elif source_type == "sample_json":
        sample = tool_input["sample_data"]

    # 2. Infer schema
    fields = infer_from_json(sample)

    # 3. Register bronze entity
    entity = create_entity({name, layer: "bronze", fields, namespace, collection}, tenant_id)

    # 4. Create connector
    config = {url, headers, json_path, pagination}  # for api_pull
    connector = create_integration({name, connector_type, entity_id, config}, tenant_id)

    # 5. Ingest data
    if source_type == "api_pull":
        result = land_api_pull(url, headers, name, tenant_id, connector_id, json_path, pagination)
    elif source_type == "webhook" or source_type == "sample_json":
        for record in data:
            land_webhook(name, record, {}, tenant_id, connector_id)

    # 6. Generate silver transform SQL
    if not skip_transform:
        pk_field = detect_primary_key(fields) or primary_key_field
        sql = generate_flatten_sql(name, fields, pk_field, tenant_id)
        # CREATE TABLE IF NOT EXISTS silver.{name} (...); INSERT OR REPLACE INTO silver.{name} SELECT ...

        transform = create_transform({
            name: f"flatten_{name}",
            sql, source_layer: "bronze", target_layer: "silver",
            trigger_mode: "on_change",
            watch_entities: [entity_id]
        }, tenant_id, created_by)

        # 7. Register silver entity
        silver_entity = create_entity({name, layer: "silver", fields: typed_fields}, tenant_id)

    # 8. Return summary
    return json.dumps({
        "entity_id": entity_id,
        "connector_id": connector_id,
        "rows_landed": total_landed,
        "transform_id": transform_id,  # if created
        "transform_status": "draft — needs admin approval",
        "silver_entity_id": silver_entity_id,
        "steps_completed": steps,
        "next_step": "Approve the transform, then it will auto-run on every new ingest."
    })
```

### SQL generation helper (new: `services/api/src/agent/handlers/flatten_sql.py`)

Generates the mandatory two-statement upsert pattern:

```python
def generate_flatten_sql(entity_name: str, fields: list[dict], pk_field: str, tenant_id: str) -> str:
    """Generate bronze→silver flattening SQL from inferred schema."""

    schema = layer_schema("silver", tenant_id)
    bronze_schema = layer_schema("bronze", tenant_id)

    # Map inferred types to DuckDB types
    type_map = {"string": "VARCHAR", "int": "BIGINT", "float": "DOUBLE",
                "bool": "BOOLEAN", "timestamp": "TIMESTAMP", "json": "JSON", "array": "JSON"}

    # Statement 1: CREATE TABLE IF NOT EXISTS
    col_defs = []
    for f in fields:
        ddb_type = type_map.get(f["data_type"], "VARCHAR")
        pk = " PRIMARY KEY" if f["name"] == pk_field else ""
        col_defs.append(f"    {f['name']} {ddb_type}{pk}")

    create_stmt = f"CREATE TABLE IF NOT EXISTS {schema}.{entity_name} (\n" + ",\n".join(col_defs) + "\n)"

    # Statement 2: INSERT OR REPLACE with json_extract
    select_cols = []
    for f in fields:
        if f["data_type"] in ("int", "float", "bool", "timestamp"):
            ddb_type = type_map[f["data_type"]]
            select_cols.append(f"    CAST(json_extract(payload, '$.{f['name']}') AS {ddb_type}) AS {f['name']}")
        else:
            select_cols.append(f"    json_extract_string(payload, '$.{f['name']}') AS {f['name']}")

    insert_stmt = (
        f"INSERT OR REPLACE INTO {schema}.{entity_name}\nSELECT\n"
        + ",\n".join(select_cols)
        + f"\nFROM {bronze_schema}.{entity_name}"
        + f"\nWHERE json_extract_string(payload, '$.{pk_field}') IS NOT NULL"
    )

    return f"{create_stmt};\n\n{insert_stmt};"
```

### Primary key detection heuristic

```python
def detect_primary_key(fields: list[dict]) -> str | None:
    """Guess the PK from field names. Returns None if ambiguous."""
    names = [f["name"] for f in fields]
    # Exact "id" field
    if "id" in names:
        return "id"
    # Fields ending in _id where the prefix matches the entity name
    for n in names:
        if n.endswith("_id") and n != "tenant_id":
            return n
    # UUID/key fields
    for n in names:
        if any(n.endswith(s) for s in ("_uuid", "_key", "_ref")):
            return n
    return None
```

### Files to change

| File | Change |
|------|--------|
| `services/api/src/agent/handlers/smart_import.py` | **NEW** — composite handler |
| `services/api/src/agent/handlers/flatten_sql.py` | **NEW** — SQL generation helper |
| `services/api/src/agent/handlers/__init__.py` | Register smart_import handler |
| `services/api/src/agent/tools.py` | Add `smart_import` tool definition |
| `services/api/src/agent/prompt.py` | Update import flow to recommend `smart_import` as primary path; keep individual tools as fallback |

### Tests
- `test_smart_import_api_pull` — end-to-end with mocked HTTP; verify entity + connector + transform created
- `test_smart_import_sample_json` — inline data; verify ingest + transform
- `test_smart_import_skip_transform` — `skip_transform=true` skips silver step
- `test_smart_import_primary_key_detection` — various field patterns
- `test_generate_flatten_sql` — verify correct two-statement upsert SQL for different field types
- `test_smart_import_duplicate_name` — entity already exists → graceful error

---

## Work Stream 4: Agent Prompt Updates

### Changes to system prompt

1. **New primary import path**: Recommend `smart_import` as the one-shot tool for all imports
2. **Keep individual tools**: Document them as fallback for partial operations or updates
3. **Remove CSV format documentation**: Everything is now webhook format
4. **Document pagination**: Show example config for api_pull with pagination
5. **Simplify SQL rules**: Remove dual-format handling

### Updated import flow section

```
## Data import flow

### One-shot import (recommended)
Use `smart_import` for end-to-end data pipeline setup. It handles:
- API discovery and pagination
- Schema inference
- Entity registration (bronze + silver)
- Connector creation
- Initial data ingestion
- Auto-generated bronze→silver flattening transform (on_change)

Ask the user for:
1. Entity name (what to call this data)
2. Source: API URL or sample JSON payload
3. For APIs: json_path to records, auth headers, pagination strategy
4. Primary key field (or let it auto-detect)

### Manual steps (fallback)
Individual tools remain available for:
- Updating existing connectors/transforms
- Re-running transforms
- Custom silver/gold transforms beyond simple flattening
```

---

## Implementation Order

1. **WS2 first** — Uniform payload format (batch_csv → webhook format). This is a prerequisite for WS3's SQL generation (only one format to handle).
2. **WS1 second** — Paginated API pull. Independent of WS2 but needed by WS3.
3. **WS3 third** — Smart import tool. Depends on WS1 (pagination) and WS2 (uniform format).
4. **WS4 last** — Prompt updates. Depends on all above being complete.

## Testing Strategy

- All new tests in `services/api/tests/test_smart_import.py`
- Pagination tests in `services/api/tests/test_paginated_api_pull.py`
- Run full suite: `cd services/api && pytest` — must be all green
- Run lint: `make lint` (if available) or `ruff check`

## Migration

No database migrations needed. All changes are in application code:
- Connector `config` JSON is schema-free (pagination config lives there)
- No new tables or columns
- Existing batch_csv data in bronze will have old flat-column format — new ingests will use payload format. This is fine since transforms reference column names explicitly.
