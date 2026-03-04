# CLAUDE.md — Project Context for Claude Code

## What This Is

Jonas Data Platform — an AI-native, multi-tenant data platform prototype.
The agent (Claude) helps permissioned users extend the system: ingest data,
create schemas, draft transforms, query across domains. All within RBAC boundaries.

## Read First

Before writing any code, read these docs in order:
1. `docs/core-abstractions.md` — architecture and the six primitives
2. `docs/demo-spec.md` — what we're building and why
3. `db/001_core.sql` — data model (PostgreSQL DDL, needs DuckDB adaptation)

## Current State

- Monorepo structure in place (apps/ + services/)
- Data model designed (13 tables across 6 domains)
- Phase 1 skeleton complete: FastAPI service + React dashboard scaffolded
- Next: adapt DDL for DuckDB, wire up MotherDuck, build out Phase 2 agent core

## Phase 1 Status (DONE)

1. ✅ **Project scaffolding**: `services/api/` with FastAPI, duckdb, pyarrow deps
2. ⏳ **MotherDuck DDL**: adapt `db/001_core.sql` → `db/001_core_duckdb.sql`
3. ✅ **FastAPI skeleton**: auth middleware, permissions, all domain routers
4. ✅ **Sample data generators**: `services/api/scripts/seed_data.py`
5. ✅ **Ingest endpoints**: webhook + batch CSV/JSON → bronze

## Next Steps (Phase 2)

- Adapt DDL to DuckDB syntax (`db/001_core_duckdb.sql`)
- Run `services/api/src/db/init.py` bootstrap against MotherDuck
- Implement schema inference in the agent
- Build NL-to-SQL scoped to user's accessible entities

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
│   └── dashboard/            ← Vite + React SPA
│       ├── src/
│       │   ├── main.tsx
│       │   ├── App.tsx
│       │   └── pages/        ← CataloguePage, IntegrationsPage, TransformsPage, ChatPage
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
│       │   ├── agent/        ← Claude API, tools, router
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
├── pnpm-workspace.yaml       ← JS monorepo workspace config
├── package.json              ← root scripts
├── .env.example
├── .gitignore
└── CLAUDE.md
```

### Commands

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

**Data volumes (local)**
```
data/db/jonas.duckdb   ← DuckDB file (git-ignored)
data/parquet/          ← parquet storage (git-ignored)
```
