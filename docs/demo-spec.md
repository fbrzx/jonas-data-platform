# Jonas Data Platform — Demo Specification

## Objective

Demonstrate an AI-native, multi-tenant data platform where an agent helps
permissioned users extend the system through conversation. The demo must prove
three things:

1. **Heterogeneous data ingestion** — different shapes, different sources
2. **Medallion refinement with approval gates** — bronze → silver → gold via agent-drafted transforms
3. **Permission-aware querying and extension** — NL-to-SQL, PII masking, cross-domain joins

## Stack

| Component | Technology | Role |
|-----------|-----------|------|
| Analytical engine | DuckDB (local) | Transforms, queries, schema inspection |
| Cloud persistence | MotherDuck | Shared storage, tenant isolation via databases |
| Agent interface | Web UI (React + chat panel) | User interaction |
| API layer | FastAPI (Python) | Auth middleware, agent orchestration |
| Agent backend | Claude API | NL understanding, SQL generation, schema proposals |
| Data format | Parquet | Bronze & silver storage in MotherDuck |

### MotherDuck Database Layout

```
md:platform_db              ← catalogue, permissions, audit, templates
md:tenant_{slug}            ← per-tenant data
  ├── bronze schema         ← raw landed data (parquet-backed tables)
  ├── silver schema         ← cleaned, typed, deduped
  └── gold schema           ← business views & materialised aggregations
```

## Data Sources (Heterogeneous)

### Source 1: E-commerce Orders (structured, transactional)
- **Inbound mode**: Realtime (webhook simulation)
- **Shape**: Nested JSON — order header with line_items array
- **Sample fields**: order_id, customer_email, total, currency, line_items[].sku,
  line_items[].qty, line_items[].price, placed_at
- **Bronze→Silver**: Flatten line items, parse timestamps, type numerics, dedup on order_id
- **Proves**: Schema inference on nested JSON, flattening transforms

### Source 2: IoT Sensor Readings (time-series, high-volume)
- **Inbound mode**: Batch (CSV upload)
- **Shape**: Flat CSV — one row per reading
- **Sample fields**: sensor_id, location, metric_name, value, unit, recorded_at
- **Bronze→Silver**: Type casting, null handling, range validation (reject impossible values)
- **Proves**: Batch integration, time-series patterns, validation transforms

### Source 3: CRM Contacts (semi-structured, PII-heavy)
- **Inbound mode**: Batch (API-style JSON array)
- **Shape**: Variable fields per record — some contacts have phone, some have
  company, some have both, some have custom fields
- **Sample fields**: contact_id, first_name, last_name, email, phone (nullable),
  company (nullable), tags[], custom_fields{}
- **Bronze→Silver**: Normalise variable fields, flag PII (email, phone, name), dedup on email
- **Proves**: Schema-on-read, PII detection and masking, permission-gated access

## Demo Scenarios

### Scenario 1: Bootstrap & Ingest (Admin persona)

**Goal**: Prove the platform can ingest heterogeneous data through agent-guided setup.

Steps:
1. Admin logs in, sees empty tenant dashboard
2. Admin says: *"I want to bring in our e-commerce order data from webhooks"*
3. Agent: selects Webhook Inbound template, asks clarifying questions about payload shape
4. Admin pastes a sample JSON order payload
5. Agent: inspects the JSON, proposes a bronze entity schema (orders_raw), shows the
   field definitions including nested line_items
6. Admin approves → integration + entity created, status: active
7. Demo fires 50 sample webhook events → data lands in bronze
8. Agent confirms: *"50 orders landed in bronze.ecommerce_orders. I can see nested line
   items — want me to set up the silver layer?"*

Repeat abbreviated flow for IoT CSV upload and CRM JSON import to show heterogeneity.
Each source gets its own namespace (ecommerce, iot, crm).

**What's demonstrated**: Integration templates, schema inference, agent-guided setup,
multi-source ingestion, catalogue population.

### Scenario 2: Refine (Engineer persona)

**Goal**: Prove the medallion transform lifecycle with approval gates.

Steps:
1. Engineer logs in, sees three bronze entities across three namespaces
2. Engineer says: *"Clean up the orders data for analysis"*
3. Agent: queries the catalogue for bronze.ecommerce_orders fields, drafts a SQL
   transform that:
   - Flattens line_items into a separate silver entity (order_lines)
   - Casts placed_at to timestamp, total to decimal
   - Deduplicates on order_id
   - Creates silver.orders and silver.order_lines entities
4. Agent shows the SQL and proposed silver schemas for review
5. Engineer says: *"Looks good, submit it"*
6. Agent: creates transform with status=draft, logs the action
7. Agent: *"This needs admin approval before it runs. I've notified the approvers."*

8. Switch to Admin persona → Admin sees pending transform
9. Admin approves → transform runs → silver entities populated
10. Agent: *"Transform complete. 50 orders → 50 order headers + 142 line items in silver.
    Lineage recorded."*

Repeat for IoT (windowed cleaning, range validation) and CRM (PII flagging).

**What's demonstrated**: Agent-drafted SQL transforms, schema creation, approval workflow,
lineage tracking, execution history.

### Scenario 3: Query, Extend & Permissions (Analyst + Viewer personas)

**Goal**: Prove NL-to-SQL, cross-domain gold views, PII masking, and permission boundaries.

**Part A — Analyst queries and extends**:
1. Analyst logs in, sees silver entities across all three namespaces
2. Analyst says: *"What were total sales by day last month?"*
3. Agent: generates SQL against silver.orders, returns results with chart
4. Analyst says: *"I want a gold view that correlates sensor alerts with affected orders
   and includes customer contact details"*
5. Agent:
   - Identifies the join path: gold.sensor_alerts (needs creating) → silver.orders
     via timestamp window → silver.crm_contacts via customer_email
   - Proposes a gold materialised view with the join logic
   - Flags that crm_contacts.email and crm_contacts.phone are PII fields
   - Shows the SQL and proposed gold entity schema
6. Analyst approves → submitted for admin approval
7. Admin approves → gold view materialised
8. Agent: *"Gold view 'order_alert_contacts' is live. Note: PII fields (email, phone)
   will be masked for users without PII access."*

**Part B — Permission boundary**:
1. Switch to Viewer persona
2. Viewer says: *"Show me the order alert contacts view"*
3. Agent: runs the query but masks email → "j***@example.com", phone → "***-***-1234"
4. Viewer says: *"Show me the raw CRM contacts"*
5. Agent: *"You don't have access to silver-layer data. You can query gold views.
   Contact your admin if you need broader access."*
6. Viewer says: *"Create a new aggregation view"*
7. Agent: *"Your role (viewer) doesn't have permission to create entities.
   I can help you draft a request to send to your team's engineer."*

**What's demonstrated**: NL-to-SQL, cross-domain joins, PII masking per-permission,
role-based access control, graceful denial with helpful alternatives.

---

## Web UI Design

### Layout

```
┌─────────────────────────────────────────────────────────┐
│  [Logo] Jonas Data Platform    [Tenant: Acme]  [User ▾] │
├──────────────┬──────────────────────────────────────────┤
│              │                                          │
│  SIDEBAR     │  MAIN PANEL                              │
│              │                                          │
│  ▸ Dashboard │  Context-dependent:                      │
│  ▸ Catalogue │  - Chat + results when talking to agent  │
│    └ namespaces│  - Data grid when browsing entities    │
│    └ entities│  - Transform editor when reviewing SQL   │
│    └ lineage │  - Run history when checking status      │
│  ▸ Integrations│                                        │
│  ▸ Transforms│ ┌──────────────────────────────────────┐ │
│  ▸ Audit Log │ │                                      │ │
│              │ │  CHAT PANEL (collapsible, right-dock) │ │
│  ─────────── │ │  Agent conversation with context      │ │
│  Role: admin │ │  awareness of current view            │ │
│  Namespace:  │ │                                      │ │
│   [all ▾]    │ │  [Message input]              [Send] │ │
│              │ └──────────────────────────────────────┘ │
├──────────────┴──────────────────────────────────────────┤
│  Status bar: MotherDuck ● connected │ 3 namespaces │    │
└─────────────────────────────────────────────────────────┘
```

### Key UI Components

1. **Chat Panel** — Right-docked, collapsible. The agent sees which page/entity
   the user is currently viewing and uses it as implicit context. Messages
   render markdown, SQL with syntax highlighting, and inline data tables.

2. **Catalogue Browser** — Tree view: Tenant → Namespace → Entity (with layer badge).
   Clicking an entity shows fields, lineage, and recent data preview.

3. **Transform Viewer** — Shows SQL with diff highlighting when agent proposes changes.
   Approve/reject buttons for admins. Execution timeline for runs.

4. **Integration Dashboard** — Cards per integration showing status, last run stats,
   next scheduled run. Click to see run history and config.

5. **Data Preview** — When an entity is selected, shows a paginated grid of recent
   records. PII fields masked based on current user's permissions.

6. **Lineage Graph** — Visual DAG showing bronze→silver→gold flow per namespace,
   with transforms on the edges. Clickable nodes.

---

## Sample Data Specifications

### E-commerce Orders (50 records)
```json
{
  "order_id": "ORD-2025-00042",
  "customer_email": "jane.doe@example.com",
  "total": 149.97,
  "currency": "GBP",
  "status": "confirmed",
  "placed_at": "2025-03-04T14:23:00Z",
  "line_items": [
    {"sku": "WIDGET-A", "name": "Widget Alpha", "qty": 2, "unit_price": 49.99},
    {"sku": "GADGET-B", "name": "Gadget Beta", "qty": 1, "unit_price": 49.99}
  ],
  "shipping": {"method": "express", "address_city": "London"}
}
```

### IoT Sensor Readings (500 records)
```csv
sensor_id,location,metric_name,value,unit,recorded_at
SENS-T-001,warehouse-north,temperature,22.4,celsius,2025-03-04T10:00:00Z
SENS-H-003,warehouse-north,humidity,45.2,percent,2025-03-04T10:00:00Z
SENS-T-001,warehouse-north,temperature,87.3,celsius,2025-03-04T10:01:00Z  # invalid
```

### CRM Contacts (100 records)
```json
{
  "contact_id": "CRM-00891",
  "first_name": "Jane",
  "last_name": "Doe",
  "email": "jane.doe@example.com",
  "phone": "+44 7700 900123",
  "company": "Acme Corp",
  "tags": ["vip", "enterprise"],
  "custom_fields": {"preferred_contact": "email", "account_tier": "gold"}
}
```

---

## Demo Users & Permissions

| User | Role | Can Do | Cannot Do |
|------|------|--------|-----------|
| alice@acme.com | owner | Everything | — |
| bob@acme.com | engineer | Create entities, draft transforms & integrations | Approve, manage users |
| carol@acme.com | analyst | Query silver+gold, draft gold views | Create bronze entities, modify integrations |
| dave@acme.com | viewer | Query gold (PII masked) | Write anything, see silver/bronze |

## Implementation Phases

### Phase 1: Foundation (build first)
- [ ] MotherDuck database setup (platform_db + tenant_acme)
- [ ] DDL migration to MotherDuck (adapted from 001_core.sql)
- [ ] FastAPI skeleton with tenant-aware auth middleware (JWT or simple token)
- [ ] Permission resolution service
- [ ] Sample data generators (orders, sensors, contacts)

### Phase 2: Agent Core
- [ ] Claude API integration with system prompt containing catalogue context
- [ ] Schema inference tool (inspect JSON/CSV → propose entity_field definitions)
- [ ] SQL generation tool (NL → DuckDB SQL, scoped to user's accessible entities)
- [ ] Transform lifecycle (draft → approve → execute → record lineage)
- [ ] PII masking in query results based on resolved permissions

### Phase 3: Web UI
- [ ] React app shell with sidebar navigation
- [ ] Chat panel with markdown/SQL/table rendering
- [ ] Catalogue browser (namespace → entity → fields tree)
- [ ] Integration dashboard with status cards
- [ ] Transform viewer with SQL diff and approve/reject
- [ ] Data preview grid with PII masking
- [ ] Lineage DAG visualisation

### Phase 4: Demo Polish
- [ ] Pre-seeded demo data (50 orders, 500 sensor readings, 100 contacts)
- [ ] Scripted demo walkthrough matching the three scenarios
- [ ] Error states and edge cases (rejected transforms, failed integrations)
- [ ] Demo reset capability (wipe and reseed)

---

## Open Questions

1. **MotherDuck auth model** — service token for the API, or per-user tokens?
   Likely: single service token, permission enforcement in the application layer.

2. **Agent memory** — should the agent remember conversation context across
   sessions, or is session-scoped sufficient for the demo? Session-scoped is simpler.

3. **Realtime webhook simulation** — actual HTTP endpoint, or mock event queue?
   Recommend: actual FastAPI endpoint that accepts POST and lands to bronze.

4. **Transform execution** — DuckDB CTAS into MotherDuck, or local DuckDB
   writing parquet then syncing? CTAS is simpler if MotherDuck handles it.
