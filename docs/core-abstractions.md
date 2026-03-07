# Jonas Data Platform — Core Abstractions

## The Six Primitives

Everything in the platform reduces to six core abstractions. The agent, API, and UI all operate through these — there are no backdoors.

### 1. Tenant
The isolation boundary. Every resource belongs to exactly one tenant. Storage is physically separated via **schema-per-tenant**: each tenant gets `bronze_{tenant_id}`, `silver_{tenant_id}`, `gold_{tenant_id}` schemas, provisioned on bootstrap. Platform metadata (catalogue, permissions, audit) lives in shared schemas with tenant_id foreign keys.

A tenant's `config` (stored in `platform.tenant_config`) holds LLM provider/model settings, PII toggle, and usage limits. Managed via the Tenant Config admin page.

**Parquet path convention**:
```
{tenant.storage_prefix}/{namespace.name}/{entity.name}/{layer}/
    YYYY/MM/DD/part-NNNN.parquet
```

### 2. Namespace + Entity + Field (The Catalogue)
The schema catalogue is the platform's self-knowledge. The agent queries it to understand what data exists, what shape it has, and where it lives.

- **Namespace**: Logical grouping (sales, marketing, ops). Maps to a directory tier in parquet paths.
- **Entity**: A dataset at a specific medallion layer. The same conceptual thing (e.g. "orders") exists as separate entities at bronze, silver, and gold — linked by lineage.
- **Field**: Column definitions. `is_pii` drives automatic masking in queries for users without PII access. `data_type` is a platform-level type that maps to both Parquet types and DuckDB types.

**Versioning**: `entity.version` increments on schema changes. The `meta` JSON on entity stores a frozen snapshot of fields at each version, enabling schema evolution without breaking existing consumers.

### 3. Transform
The mechanism that moves data between medallion layers. A transform is a unit of work that reads from a source entity and writes to a target entity.

**Types**:
- `sql`: Executed by DuckDB. Most transforms are this — SELECT with cleaning, typing, dedup, aggregation.
- `python`: For complex logic the agent can generate. Runs in a sandboxed subprocess.
- `dbt_ref`: Reference to an external dbt model (placeholder, not yet implemented).

**Lifecycle**: draft → approved → (executed). The approval gate means an engineer can draft a transform and an admin must approve before it touches production data. The agent can draft transforms; it cannot self-approve.

**Trigger modes**:
- `manual`: Runs on demand or via cron schedule
- `on_change`: Event-driven — automatically fires when a watched entity receives new data (with 30s debounce, cascade cap of 5, cycle guard)

**SQL validation**: Transform SQL is validated on create and execute — `DROP`, `DELETE`, `UPDATE`, `TRUNCATE` are blocked.

### 4. Connector
The bridge between the platform and the outside world. Connectors bring data in.

**Types**:
- `webhook`: Receives POST payloads, lands JSON into bronze
- `batch`: Accepts CSV/JSON file uploads
- `api_pull`: Pulls data from external APIs (with SSRF protection — blocks private/loopback IPs)

Each connector is linked to a target entity in the catalogue. Connectors support:
- **Cron scheduling**: `cron_schedule` field for automated runs
- **Run history**: Full `connector_run` lifecycle records
- **Agent-guided setup**: The agent can discover APIs, propose schemas, and create connectors via `jonas-form` interactive cards

### 5. Permission Grant
Fine-grained access control layered on top of the role hierarchy.

**Role hierarchy** (on `tenant_membership`):
- `admin`: Full control — manage users, approve transforms/connectors, all layer access, PII visible
- `analyst`: Query silver+gold layers, PII masked
- `viewer`: Read-only on gold layer, PII masked

**SQL scope enforcement**: The agent enforces layer access at query time — analysts cannot SELECT from bronze tables, viewers cannot SELECT from bronze or silver.

**PII masking**: Fields marked `is_pii` are automatically masked (email → `j***@example.com`, phone → `***-***-1234`) for non-admin users. Admins/owners see raw data.

### 6. Audit Log
Append-only. Every mutation, query, approval, and agent action is recorded. The audit system includes:
- **Audit logs**: Action/entity_type filterable, paginated
- **Job history**: Unified view of connector runs + transform runs
- **Agent memory**: Persistent memory across sessions (save/recall/forget with keyword relevance + score decay)

---

## How the Agent Fits

The agent is NOT a superuser. It operates as a proxy for the authenticated user, inheriting their resolved permission set.

**Capabilities** (14 tools):
- Schema: `infer_schema`, `register_entity`, `preview_entity`
- Query: `run_sql` (SELECT-only, layer-scoped)
- Transforms: `draft_transform`, `list_transforms`, `update_transform`
- Connectors: `list_connectors`, `get_connector_runs`, `ingest_webhook`, `create_connector`, `discover_api`
- Memory: `save_memory`, `recall_memory`, `forget_memory`

**LLM providers**: OpenAI, Google (Gemini), Ollama (local models). Configured per-tenant via Tenant Config page.

**Streaming**: SSE-based chat with `tool`/`delta`/`done` events. Interactive `jonas-form` cards for guided data import flows.

## Medallion Flow

```
External Source
      |
      v
+-----------+     connector (webhook / batch / api_pull)
|   BRONZE  | <-- raw JSON/CSV, append-only, schema-on-read
|  (table)  |     partitioned by date
+-----+-----+
      | transform (sql: clean, type, dedup)
      v           trigger: manual or on_change
+-----------+
|   SILVER  |     validated, typed, deduplicated
|  (table)  |     conformed to entity_field definitions
+-----+-----+
      | transform (sql: aggregate, join, business logic)
      v
+-----------+
|    GOLD   |     business-ready views & materialised tables
| (view/mat)|     queryable by analysts & AI applications
+-----+-----+
      | direct query / future: outbound connectors
      v
  Consumers (dashboards, APIs, GenAI apps)
```

## What's NOT in the Platform (Yet)

- **Secrets management**: auth_config stores plaintext in dev, needs Vault/KMS in production
- **Outbound connectors**: Only inbound currently (webhook, batch, api_pull)
- **CDC / streaming**: Realtime inbound is webhooks only
- **dbt integration**: `transform_type='dbt_ref'` is a placeholder
- **Schema evolution tooling**: Version tracking exists but migration tooling doesn't
- **Data visualisation**: Tabular data preview only — D3/Observable charts planned (Phase 8)
- **Storage abstraction**: Locked to local DuckDB — MotherDuck/cloud parquet planned (Phase 9)
- **Owner/engineer roles**: RBAC code enforces admin/analyst/viewer only
