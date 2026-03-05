# CLAUDE.md — Project Context for Claude Code

## What This Is

Jonas Data Platform — an AI-native, multi-tenant data platform prototype.
The agent (Claude) helps permissioned users extend the system: ingest data,
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

## Phase 1 Status (DONE)

1. ✅ **Project scaffolding**: `services/api/` with FastAPI, duckdb, pyarrow deps
2. ✅ **MotherDuck DDL**: `db/001_core_duckdb.sql` fully adapted from PostgreSQL
3. ✅ **FastAPI skeleton**: auth middleware, permissions, all domain routers
4. ✅ **Sample data generators**: `services/api/scripts/seed_data.py`
5. ✅ **Ingest endpoints**: webhook + batch CSV/JSON → bronze

## Phase 2 Status (DONE)

1. ✅ **Agent core** (`services/api/src/agent/`): tool-use loop via Claude API
   - 7 tools: `list_entities`, `describe_entity`, `infer_schema`, `register_entity`, `run_sql`, `preview_entity`, `draft_transform`
   - Dynamic system prompt with live catalogue context
   - Role-scoped SQL enforcement (bronze/silver/gold layer access by role)
2. ✅ **Schema inference** (`agent/inference.py`): JSON/CSV → field definitions with type detection + PII heuristics
3. ✅ **PII masking** (`agent/pii.py`): deterministic field-level masking; owners/admins see raw data
4. ✅ **NL-to-SQL**: `run_sql` tool enforces SELECT-only + layer RBAC
5. ✅ **Dashboard enhanced**: DashboardPage (stats + quick actions), LineagePage (medallion flow)

## Next Steps (Phase 3)

- Wire up MotherDuck: run `services/api/src/db/init.py` bootstrap against live MD instance
- End-to-end demo: seed → ingest → agent registers entity → transform draft → approval
- Add transform execution (run approved transforms against DuckDB)
- Streaming chat responses (SSE) for long-running queries

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
- Environment config via .env file (MOTHERDUCK_TOKEN, CLAUDE_API_KEY)
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
│       │   │   ├── service.py    ← Claude API tool-use loop
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
