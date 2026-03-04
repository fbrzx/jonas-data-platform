# Jonas Data Platform

AI-native, multi-tenant data platform where an agent helps permissioned users
extend the system through conversation — schema, integrations, transforms, queries.

## Vision

A data platform that treats the AI agent as a first-class citizen, not a bolt-on.
Users interact with the agent to ingest heterogeneous data sources, refine them
through a medallion architecture (bronze → silver → gold), and query across domains
— all within a permission boundary where the agent inherits the authenticated
user's access level.

## Stack

| Component | Technology |
|-----------|-----------|
| Analytical engine | DuckDB (local) |
| Cloud persistence | MotherDuck (one database per tenant) |
| API layer | FastAPI (Python) — `services/api/` |
| Agent backend | Claude API (`claude-sonnet-4-6`) |
| Web UI | Vite + React + TypeScript — `apps/dashboard/` |
| Data format | Parquet (bronze/silver), views/materialised (gold) |

## Quick Start

```bash
# 1. Install JS dependencies (from repo root)
pnpm install

# 2. Start the dashboard
pnpm dev                  # http://localhost:5173

# 3. In another terminal, start the API
cd services/api
pip install -e ".[dev]"
python -m uvicorn src.main:app --reload   # http://localhost:8000

# 4. Generate sample data
python scripts/seed_data.py
```

Copy `.env.example` to `.env` and fill in `MOTHERDUCK_TOKEN` and `CLAUDE_API_KEY`.

## MotherDuck Layout

```
md:platform_db              ← catalogue, permissions, audit, templates
md:tenant_{slug}            ← per-tenant data
  ├── bronze schema         ← raw landed data
  ├── silver schema         ← cleaned, typed, deduped
  └── gold schema           ← business views & materialised aggregations
```

## Documentation

Read these in order:

1. **`docs/core-abstractions.md`** — The six primitives (Tenant, Catalogue,
   Transform, Integration, Permission, Audit), how the agent's permissions work,
   medallion flow, and what's explicitly out of scope.

2. **`docs/data-model.mermaid`** — ER diagram of all 13 tables. Render in any
   Mermaid viewer or Obsidian.

3. **`docs/demo-spec.md`** — Full demo specification: three heterogeneous data
   sources (e-commerce orders, IoT sensors, CRM contacts), three scenarios
   (bootstrap, refine, query+extend), four user personas, web UI wireframe,
   sample data shapes, and implementation phases.

4. **`db/001_core.sql`** — PostgreSQL-flavoured DDL (needs adapting for DuckDB/
   MotherDuck syntax). 13 tables with design rationale in comments.

## Implementation Phases

### Phase 1: Foundation (start here)
- MotherDuck database setup (platform_db + tenant_acme)
- Adapt DDL from 001_core.sql to DuckDB/MotherDuck syntax
- FastAPI skeleton with tenant-aware auth middleware (JWT or simple token)
- Permission resolution service
- Sample data generators (50 orders, 500 sensor readings, 100 contacts)

### Phase 2: Agent Core
- Claude API integration with catalogue-aware system prompt
- Schema inference (inspect JSON/CSV → propose entity fields)
- NL-to-SQL (scoped to user's accessible entities)
- Transform lifecycle (draft → approve → execute → lineage)
- PII masking in query results

### Phase 3: Web UI (scaffold complete)
- ✅ Vite + React SPA skeleton (`apps/dashboard/`)
- ✅ Sidebar nav with stub pages: Catalogue, Integrations, Transforms, Chat
- Catalogue browser, integration dashboard, transform viewer (TODO)
- Data preview grid with PII masking (TODO)
- Lineage DAG visualisation (TODO)

### Phase 4: Demo Polish
- Pre-seeded demo data
- Scripted walkthrough for the three scenarios
- Demo reset capability

## Key Design Decisions

- **DuckDB + MotherDuck only** — no Postgres for the prototype. Transactional
  guarantees are weaker but adequate for demonstrating the concept.
- **Shared-schema multi-tenancy** in platform_db, physical isolation via
  separate MotherDuck databases per tenant.
- **Agent inherits user permissions** — cannot escalate, can draft but not
  self-approve transforms or integrations.
- **JSONB/JSON for extensibility** — tenant config, entity metadata, integration
  configs, audit details.
- **Approval gates** on transforms and integrations — engineer drafts, admin
  approves before execution.

## Open Questions (for implementer)

1. **MotherDuck auth**: Service token for API, enforce permissions in app layer.
2. **Transform execution**: DuckDB CTAS into MotherDuck vs local parquet + sync.
3. **Webhook simulation**: Real FastAPI POST endpoint landing to bronze.
4. **Agent memory**: Session-scoped for demo (no cross-session persistence).
