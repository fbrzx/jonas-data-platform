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

**Role hierarchy** (on `tenant_membership`): `owner > admin > engineer > analyst > viewer`

| Role | Layer access | PII | Approve | User admin |
|------|-------------|-----|---------|------------|
| owner | all | visible | yes | yes |
| admin | all | visible | yes | no |
| engineer | all | masked | yes | no |
| analyst | silver + gold | masked | no | no |
| viewer | gold only | masked | no | no |

**SQL scope enforcement**: The agent enforces layer access at query time — analysts cannot SELECT from bronze tables, viewers cannot SELECT from bronze or silver.

**PII masking**: Fields marked `is_pii` are automatically masked (email → `j***@example.com`, phone → `***-***-1234`) for roles without PII access. Owner and admin see raw data.

**Frontend gates** (`usePermissions` hook):
- `canWrite` — analyst and above; controls write actions (upload, trigger)
- `canApprove` — engineer and above; controls approve/edit actions
- `canAdmin` — admin and above; controls delete and user management

### 6. Audit Log
Append-only. Every mutation, query, approval, and agent action is recorded. The audit system includes:
- **Audit logs**: Action/entity_type filterable, paginated
- **Job history**: Unified view of connector runs + transform runs
- **Agent memory**: Persistent memory across sessions (save/recall/forget with keyword relevance + score decay)

---

## How the Agent Fits

The agent is NOT a superuser. It operates as a proxy for the authenticated user, inheriting their resolved permission set.

**Capabilities** (18 tools):
- Schema: `infer_schema`, `register_entity`, `preview_entity`
- Query: `run_sql` (SELECT-only, layer-scoped)
- Transforms: `draft_transform`, `list_transforms`, `update_transform`
- Connectors: `list_connectors`, `get_connector_runs`, `ingest_webhook`, `create_connector`, `discover_api`
- Memory: `save_memory`, `recall_memory`, `forget_memory`
- Collections: `assign_collection`
- Dashboards: `create_dashboard`

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

- **Outbound connectors**: Only inbound currently (webhook, batch, api_pull)
- **CDC / streaming**: Realtime inbound is webhooks only — no Kafka/Kinesis integration
- **dbt integration**: `transform_type='dbt_ref'` is a placeholder, not implemented
- **Schema evolution tooling**: Version tracking exists but automated migration tooling doesn't
- **Proper migration framework**: DDL runs on boot; no alembic-style versioned migrations
- **CI/CD**: No automated build/test/deploy pipeline yet (Phase 10)
- **Observability**: No structured logging, metrics, or tracing (Phase 10)
- **Metadata in Postgres**: All data (platform + analytical) lives in DuckDB; splitting to Postgres + DuckDB is a future architecture option
