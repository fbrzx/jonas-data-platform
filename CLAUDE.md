# CLAUDE.md — Project Context

## What This Is

Jonas Data Platform — an AI-native, multi-tenant data platform prototype.
The agent (LLM-powered assistant) helps permissioned users extend the system: ingest data,
create schemas, draft transforms, query across domains. All within RBAC boundaries.

## Read First

Before writing any code, read these docs in order:
1. `docs/core-abstractions.md` — architecture and the six primitives
2. `docs/demo-spec.md` — what we're building and why
3. `db/001_core_duckdb.sql` — live DuckDB data model (use this, not the Postgres one)

## Current State

- Monorepo structure in place (apps/ + services/)
- Data model designed (13 tables across 6 domains)
- Phase 1 complete: FastAPI service + React dashboard fully built
- Phase 2 complete: agent core, schema inference, PII masking, NL-to-SQL, lineage view
- Phase 3 complete: streaming SSE chat, 13 agent tools, full integration + transform CRUD

## Phase 1 Status (DONE)

1. ✅ **Project scaffolding**: `services/api/` with FastAPI, duckdb, pyarrow deps
2. ✅ **MotherDuck DDL**: `db/001_core_duckdb.sql` fully adapted from PostgreSQL
3. ✅ **FastAPI skeleton**: auth middleware, permissions, all domain routers
4. ✅ **Sample data generators**: `services/api/scripts/seed_data.py`
5. ✅ **Ingest endpoints**: webhook + batch CSV/JSON → bronze

## Phase 2 Status (DONE)

1. ✅ **Agent core** (`services/api/src/agent/`): tool-use loop via provider-based LLM API (`openai`, `google`, `ollama`)
   - Dynamic system prompt with live catalogue context
   - Role-scoped SQL enforcement (bronze/silver/gold layer access by role)
2. ✅ **Schema inference** (`agent/inference.py`): JSON/CSV → field definitions with type detection + PII heuristics
3. ✅ **PII masking** (`agent/pii.py`): deterministic field-level masking; owners/admins see raw data
4. ✅ **NL-to-SQL**: `run_sql` tool enforces SELECT-only + layer RBAC
5. ✅ **Dashboard enhanced**: DashboardPage (stats + quick actions), LineagePage (medallion flow)

## Phase 3 Status (DONE)

1. ✅ **Streaming SSE chat**: `stream_chat` in `agent/service.py` — emits `tool`/`delta`/`done` events
2. ✅ **Agent tools expanded to 13**: added `list_integrations`, `get_integration_runs`, `ingest_webhook`, `create_integration`, `list_transforms`, `update_transform` (on top of original 7)
3. ✅ **Agent system prompt**: 6-step guided import flow, physical storage format docs (webhook vs batch column layout), integration/transform relationship rules
4. ✅ **Integration API**: `api_pull` connector type; linked endpoints `/{id}/webhook`, `/{id}/batch`, `/{id}/trigger`, `/{id}/runs`; source table resolved from linked entity name
5. ✅ **Transform CRUD**: `update_transform` + `delete_transform`; SQL edits reset approved transforms to draft; full `transform_run` lifecycle records with `last_run_at`
6. ✅ **TransformsPage**: create/edit modal with RBAC-aware form (SQL locked for non-admins on approved transforms); inline execute result
7. ✅ **IntegrationsPage**: upload for batch integrations, trigger for api_pull, run history display

## Next Steps (Phase 4) — **current priority**

> Full plan: [`.claude/docs/phase-4-plan.md`](.claude/docs/phase-4-plan.md)

Planned in this order:

1. **Rename integrations → connectors** — DB migration + all call sites
2. **API discovery via chat** — `discover_api` agent tool (httpx pull + schema inference) + `jonas-form` inline form card in chat
3. **Job scheduler** — APScheduler cron pulls; `cron_schedule` column on connectors; cron UI in ConnectorsPage
4. **Audit page** — chat session persistence; unified jobs/logs/conversations view
5. **Data pager** — reusable `DataPager` component; paginated preview endpoint; applied to catalogue + audit
6. **Silver transform flow** — SELECT + UPSERT-only SQL validation; guided `INSERT OR REPLACE` pattern via agent

Deferred:
- Wire up MotherDuck (when moving beyond local DuckDB)

## Phase 5 — Auth, Tenant Config & Data Segregation (future)

> Full plan: [`.claude/docs/phase-5-plan.md`](.claude/docs/phase-5-plan.md)
> **Needs detailed planning before implementation starts.**

- Real authentication — JWT login/refresh/logout replacing hardcoded demo tokens; invite-only user registration
- Tenant configuration — per-tenant LLM provider, PII settings, retention policy (admin only)
- Tenant user administration — invite, role assignment, revoke access (admin only)
- Tenant data segregation — schema-per-tenant for bronze/silver/gold physical data; RBAC audit + cross-tenant isolation tests; MotherDuck database-per-tenant path

## Technical Notes

### DuckDB/MotherDuck specifics
- Connect via `duckdb.connect('md:')` with MOTHERDUCK_TOKEN env var
- Use `CREATE SCHEMA IF NOT EXISTS` for bronze/silver/gold within tenant DBs
- DuckDB supports `CREATE TABLE ... AS SELECT` (CTAS) for transforms
- Parquet read/write is native: `COPY ... TO 'path.parquet' (FORMAT PARQUET)`
- JSON type exists but no JSONB — use JSON and json_extract functions
- UUID generation: `uuid()` not `uuid_generate_v4()`
- No INET type — use VARCHAR for ip_address
- Sequences work differently — prefer UUID PKs over serial

### Conventions
- Python 3.11+, use type hints throughout
- Pydantic models for all API request/response shapes
- Async FastAPI where possible
- Environment config via .env file (`MOTHERDUCK_TOKEN`, `LLM_PROVIDER`, `LLM_MODEL`, provider credentials)
- All SQL in the codebase should be parameterised (no f-string SQL)

### Monorepo Structure

```
jonas-data-platform/
├── apps/
│   └── dashboard/            ← Vite + React SPA (Tailwind, tanstack-query)
│       ├── src/
│       │   ├── main.tsx
│       │   ├── App.tsx
│       │   └── pages/
│       │       ├── DashboardPage.tsx   ← stats + quick actions overview
│       │       ├── CataloguePage.tsx   ← entity browser
│       │       ├── IntegrationsPage.tsx
│       │       ├── TransformsPage.tsx  ← draft/approve workflow
│       │       ├── LineagePage.tsx     ← medallion lineage graph
│       │       └── ChatPage.tsx        ← NL chat with Jonas agent
│       ├── index.html
│       ├── vite.config.ts
│       └── package.json
├── services/
│   └── api/                  ← Python FastAPI backend
│       ├── src/
│       │   ├── main.py       ← FastAPI app
│       │   ├── config.py     ← pydantic-settings env config
│       │   ├── auth/         ← middleware + permissions
│       │   ├── catalogue/    ← models, service, router
│       │   ├── integrations/ ← models, service, ingest, router
│       │   ├── transforms/   ← models, service, router
│       │   ├── agent/
│       │   │   ├── router.py     ← /agent/chat endpoint
│       │   │   ├── service.py    ← provider-based LLM tool-use loop
│       │   │   ├── tools.py      ← 7 tool definitions
│       │   │   ├── inference.py  ← JSON/CSV → field schema inference
│       │   │   └── pii.py        ← deterministic field-level PII masking
│       │   └── db/           ← connection, init
│       ├── scripts/
│       │   ├── seed_data.py  ← sample data generators
│       │   └── reset_demo.py ← wipe and reseed
│       ├── tests/
│       └── pyproject.toml
├── db/
│   ├── 001_core.sql          ← original PostgreSQL DDL (reference)
│   └── 001_core_duckdb.sql   ← adapted for DuckDB/MotherDuck ✅
├── docs/
│   ├── core-abstractions.md
│   ├── data-model.mermaid
│   └── demo-spec.md
├── docker-compose.yml        ← API service on :8000
├── Makefile                  ← dev shortcuts (make up, make demo, make seed…)
├── pnpm-workspace.yaml       ← JS monorepo workspace config
├── package.json              ← root scripts
├── .env.example
├── .gitignore
└── CLAUDE.md
```

### Commands

**Makefile shortcuts (recommended)**
```bash
make demo        # docker up + seed data in one shot
make up          # build + start Docker services (:8000)
make dev         # Vite dashboard dev server (:5173)
make seed        # generate + load sample data
make reset       # wipe data volumes and restart fresh
make logs        # tail API container logs
make shell       # open shell in API container
make test        # run Python tests
make lint        # ruff + eslint
```

**API in Docker (primary workflow)**
```bash
docker compose up --build         # build + start API on :8000
docker compose up -d              # start detached
docker compose logs -f api        # tail logs
docker compose down               # stop
```

**Dashboard (local, connects to Docker API)**
```bash
pnpm install              # install all JS deps from root
pnpm dev                  # Vite dev server on :5173, proxies /api → :8000
pnpm build                # production static build
```

**API without Docker (debugging / tests)**
```bash
cd services/api
pip install -e ".[dev]"
python -m uvicorn src.main:app --reload   # localhost:8000
python scripts/seed_data.py              # generate sample data
pytest                                    # run tests
```

**Demo tokens (hardcoded for local dev)**
```
admin-token    → role: admin   (full layer access + PII)
analyst-token  → role: analyst (silver/gold only, PII masked)
viewer-token   → role: viewer  (gold only, PII masked)
```

**Data volumes (local)**
```
data/db/jonas.duckdb   ← DuckDB file (git-ignored)
data/parquet/          ← parquet storage (git-ignored)
```
