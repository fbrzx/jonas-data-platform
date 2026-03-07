# Jonas Data Platform — Demo Specification

## Objective

Demonstrate an AI-native, multi-tenant data platform where an agent helps
permissioned users extend the system through conversation.

The demo proves three things:
1. **Heterogeneous data ingestion** — different shapes, different sources
2. **Medallion refinement with approval gates** — bronze -> silver -> gold via agent-drafted transforms
3. **Permission-aware querying and extension** — NL-to-SQL, PII masking, cross-domain joins

## Stack

| Component | Technology | Status |
|-----------|-----------|--------|
| Analytical engine | DuckDB (local) | Working |
| Cloud persistence | MotherDuck (via MOTHERDUCK_TOKEN) | Supported, untested at scale |
| Web UI | React + Vite + Tailwind + TanStack Query | Working |
| API layer | FastAPI (Python 3.11+) | Working |
| Agent backend | Multi-provider LLM (OpenAI/Google/Ollama) | Working |
| Auth | JWT (HS256) + demo tokens | Working |
| Data format | DuckDB tables (parquet export planned) | Working |

### Storage Layout (Schema-per-Tenant)

```
DuckDB database
  +-- platform schema         <-- tenant, user_account, tenant_membership, config
  +-- catalogue schema        <-- namespace, entity, entity_field, entity_lineage
  +-- transforms schema       <-- transform, transform_run
  +-- integrations schema     <-- connector, connector_run
  +-- permissions schema      <-- permission_grant
  +-- audit schema            <-- audit_log, agent_memory
  +-- bronze_{tenant_id}      <-- raw landed data (per tenant)
  +-- silver_{tenant_id}      <-- cleaned, typed, deduped (per tenant)
  +-- gold_{tenant_id}        <-- business views (per tenant)
```

## Data Sources (Seeded by `scripts/seed_data.py`)

### Source 1: E-commerce Orders (50 records)
- **Connector type**: webhook
- **Shape**: Nested JSON — order header with line_items array
- **Sample fields**: order_id, customer_email, total, currency, line_items[].sku, qty, price, placed_at

### Source 2: IoT Sensor Readings (500 records)
- **Connector type**: batch (CSV)
- **Shape**: Flat CSV — one row per reading
- **Sample fields**: sensor_id, location, metric_name, value, unit, recorded_at

### Source 3: CRM Contacts (100 records)
- **Connector type**: batch (JSON)
- **Shape**: Variable fields per record (some have phone, company, custom_fields)
- **Sample fields**: contact_id, first_name, last_name, email, phone, company, tags[]

## Demo Personas

| User | Email | Role | Access | Password |
|------|-------|------|--------|----------|
| Admin | admin@acme.io | admin | All layers, PII visible, approve/manage | admin123 |
| Analyst | analyst@acme.io | analyst | Silver+gold, PII masked | admin123 |
| Viewer | viewer@acme.io | viewer | Gold only, PII masked | admin123 |

**Demo tokens** (when `DEMO_MODE=true`, default): `admin-token`, `analyst-token`, `viewer-token`

**JWT login**: `POST /api/v1/auth/login` with email + password

## Demo Scenarios

### Scenario 1: Bootstrap & Ingest (Admin)
1. Admin logs in, sees dashboard with stats
2. Opens ChatPage, says: "I want to bring in e-commerce order data from webhooks"
3. Agent discovers API / asks for sample payload, proposes bronze entity schema
4. Agent emits `jonas-form` card for connector configuration
5. Admin fills form, connector created, data ingested
6. Agent confirms: "50 orders landed in bronze"

### Scenario 2: Refine (Admin as engineer)
1. Admin says: "Clean up the orders data for analysis"
2. Agent queries catalogue, drafts SQL transform (bronze -> silver)
3. Admin approves, transform executes
4. Silver entity populated, lineage recorded

### Scenario 3: Query & Permissions
1. Analyst logs in, queries silver/gold data via NL
2. PII fields (email, phone) automatically masked
3. Viewer logs in — can only see gold, gets graceful denial for silver/bronze
4. Viewer tries to create entity — agent explains role limitation

## Running the Demo

```bash
make demo          # docker up + seed data
make dev           # start dashboard on :5173

# Or manually:
docker compose up --build -d
pnpm dev
```

Open http://localhost:5173 — login with demo credentials or use token selector.

## Implementation Phases (all complete)

- [x] Phase 1: FastAPI + DuckDB + DDL + sample data + ingest
- [x] Phase 2: Agent core + schema inference + PII masking + NL-to-SQL
- [x] Phase 3: Streaming chat + 14 tools + transform CRUD + full dashboard
- [x] Phase 4: Connectors rename + discover_api + scheduler + audit + jonas-form
- [x] Phase 5: JWT auth + tenant config + users + invite + schema-per-tenant
- [x] Phase 6: Event-driven transforms + agent memory + refactoring + JSON skills

## What's Next

See [`.claude/docs/roadmap.md`](../.claude/docs/roadmap.md) for the forward plan:
- Phase 7: Security hardening
- Phase 8: Data visualisation (D3 / Observable)
- Phase 9: Storage abstraction
- Phase 10: Production readiness
