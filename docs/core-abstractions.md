# Jonas Data Platform — Core Abstractions

## The Six Primitives

Everything in the platform reduces to six core abstractions. The agent, API, and UI all operate through these — there are no backdoors.

### 1. Tenant
The isolation boundary. Every resource belongs to exactly one tenant. Storage is physically separated via path prefixes (parquet) and logically separated via foreign keys (Postgres). A tenant's `config` JSONB holds feature flags, quotas (max entities, max integration runs/day), and tier-specific settings.

**Key decision**: Schema-per-tenant was considered but rejected for the prototype — a shared schema with tenant_id FKs + RLS policies is simpler to manage and migrate. The parquet layer gets real isolation via path partitioning.

### 2. Namespace + Entity + Field (The Catalogue)
The schema catalogue is the platform's self-knowledge. The agent queries it to understand what data exists, what shape it has, and where it lives.

- **Namespace**: Logical grouping (sales, marketing, ops). Maps to a directory tier in parquet paths.
- **Entity**: A dataset at a specific medallion layer. The same conceptual thing (e.g. "orders") exists as separate entities at bronze, silver, and gold — linked by lineage.
- **Field**: Column definitions. `is_pii` drives automatic masking in queries for users without PII access. `data_type` is a platform-level type that maps to both Parquet types and DuckDB types.

**Versioning**: `entity.version` increments on schema changes. The `meta` JSONB on entity stores a frozen snapshot of fields at each version, enabling schema evolution without breaking existing consumers.

**Parquet path convention**:
```
{tenant.storage_prefix}/{namespace.name}/{entity.name}/{layer}/
    YYYY/MM/DD/part-NNNN.parquet
```

### 3. Transform
The mechanism that moves data between medallion layers. A transform is a unit of work that reads from a source entity and writes to a target entity.

**Types**:
- `sql`: Executed by DuckDB. Most transforms are this — SELECT with cleaning, typing, dedup, aggregation.
- `python`: For complex logic the agent can generate. Runs in a sandboxed subprocess.
- `dbt_ref`: Reference to an external dbt model, for teams already using dbt.

**Lifecycle**: draft → (approved) → active → running/paused/failed. The approval gate means an engineer can draft a transform and an admin must approve before it touches production data. The agent can draft transforms; it cannot self-approve.

**Scheduling**: Cron for batch, NULL for event-driven (triggered when source entity gets new data). `transform_run` provides full execution history.

### 4. Integration
The bridge between the platform and the outside world. Every integration is either:
- **Inbound**: Data flowing in (webhook receiver, API poller, S3 watcher, CDC listener)
- **Outbound**: Data flowing out (webhook sender, S3 exporter, API pusher, event publisher)

And either:
- **Realtime**: Triggered per-event (webhooks, CDC)
- **Batch**: Scheduled (cron-based pulls/pushes)

**Templates** are the skill library. A template defines the config schema (what fields the user needs to fill in), a default transform (how to map incoming data to bronze), and the integration type. The agent helps users select and configure templates.

**Config separation**:
- `source_config`: Where data comes from (URL, S3 bucket, API endpoint)
- `sink_config`: Where data goes (target entity, field mapping)
- `auth_config`: Credential references (never plaintext — points to a secrets manager)

### 5. Permission Grant
Fine-grained access control layered on top of the role hierarchy.

**Role hierarchy** (on `tenant_membership`):
- `owner`: Full control, can delete tenant
- `admin`: Manage users, approve transforms/integrations
- `engineer`: Create/modify entities, transforms, integrations (pending approval)
- `analyst`: Query silver+gold, create gold views
- `viewer`: Read-only on gold

**Permission grants** add exceptions in both directions:
- Grant an analyst write access to a specific namespace
- Restrict an engineer to only certain namespaces via `scope`

**Permission check algorithm**:
1. Get user's role from `tenant_membership`
2. Apply role's default permissions
3. Layer on any `permission_grant` entries matching the user (directly or via role)
4. For PII fields, check additional PII access grant
5. The agent inherits the requesting user's resolved permissions — it cannot escalate

### 6. Audit Log
Append-only, immutable. Every mutation, query, approval, and agent action is recorded with before/after snapshots. This isn't just compliance — it's how the agent explains "what happened to this data" when users ask lineage questions.

**What gets logged**:
- Schema changes (entity/field create/update/delete)
- Transform and integration lifecycle events
- Permission changes
- Data queries (query text, not results)
- Agent actions (what it did on behalf of whom)

---

## How the Agent Fits

The agent is NOT a superuser. It operates as a proxy for the authenticated user, inheriting their resolved permission set. What it can do:

| Agent Action | Required Permission |
|---|---|
| Query data | `read` on entity |
| Propose schema extension | `create` on namespace |
| Draft a transform | `write` on transform |
| Draft an integration | `write` on integration |
| Approve anything | `approve` (admin+ only) |
| Explain lineage | `read` on involved entities |

The agent's core value is in **composing** the primitives: "I want to pull data from Shopify into the platform" becomes a conversation where the agent selects the right integration template, helps configure it, proposes a bronze entity schema based on the Shopify API shape, drafts the bronze→silver transform, and submits everything for approval.

## Medallion Flow

```
External Source
      │
      ▼
┌─────────────┐     integration (inbound)
│   BRONZE    │ ◄── raw JSON/CSV, append-only, schema-on-read
│  (parquet)  │     partitioned by date
└──────┬──────┘
       │ transform (sql: clean, type, dedup)
       ▼
┌─────────────┐
│   SILVER    │     validated, typed, deduplicated
│  (parquet)  │     conformed to entity_field definitions
└──────┬──────┘
       │ transform (sql: aggregate, join, business logic)
       ▼
┌─────────────┐
│    GOLD     │     business-ready views & materialised tables
│ (view/mat)  │     queryable by analysts & AI applications
└──────┬──────┘
       │ integration (outbound) / direct query
       ▼
  Consumers (dashboards, APIs, GenAI apps)
```

## What's NOT in the Prototype (Yet)

- **Secrets management**: auth_config will store plaintext in dev, needs Vault/KMS in production
- **CDC / streaming**: realtime inbound starts as webhooks only
- **dbt integration**: transform_type='dbt_ref' is a placeholder
- **Schema evolution**: version tracking exists but migration tooling doesn't
- **RLS policies**: defined in design but not generated as SQL yet
- **Multi-region storage**: single storage root per tenant for now
