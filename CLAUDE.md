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
- Phase 4 in progress: connectors rename done, discover_api tool done, silver validation done

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
2. ✅ **Agent tools expanded to 14**: added `list_connectors`, `get_connector_runs`, `ingest_webhook`, `create_connector`, `discover_api`, `list_transforms`, `update_transform` (on top of original 7)
3. ✅ **Agent system prompt**: 6-step guided import flow, physical storage format docs (webhook vs batch column layout), connector/transform relationship rules
4. ✅ **Connector API**: `api_pull` connector type; linked endpoints `/{id}/webhook`, `/{id}/batch`, `/{id}/trigger`, `/{id}/runs`; source table resolved from linked entity name
5. ✅ **Transform CRUD**: `update_transform` + `delete_transform`; SQL edits reset approved transforms to draft; full `transform_run` lifecycle records with `last_run_at`
6. ✅ **TransformsPage**: create/edit modal with RBAC-aware form (SQL locked for non-admins on approved transforms); inline execute result
7. ✅ **ConnectorsPage**: upload for batch connectors, trigger for api_pull, run history display

## Phase 4 Status (COMPLETE)

> Full plan: [`.claude/docs/phase-4-plan.md`](.claude/docs/phase-4-plan.md)

1. ✅ **Rename integrations → connectors** — `db/002_rename_integrations.sql` migration; all service/ingest/agent/frontend call sites updated; API prefix `/api/v1/connectors`
2. ✅ **`discover_api` agent tool** — httpx pull with SSRF guard (blocks private/loopback IPs); dot-notation json_path extraction; returns sample records for schema inference
3. ✅ **`jonas-form` chat card** — agent emits ` ```jonas-form ``` ` JSON blocks; `ConnectorFormCard` renders interactive form in ChatPage; submit sends filled values back to agent
4. ✅ **Job scheduler** — APScheduler `BackgroundScheduler`; `cron_schedule` column on connectors (`db/003_cron_audit.sql`); cron UI + badge in ConnectorsPage; auto-loads jobs on startup
5. ✅ **Audit page** — `AuditPage.tsx` with Jobs + Logs tabs; `GET /api/v1/audit/jobs` (unified connector+transform runs); `GET /api/v1/audit/logs` with action/entity_type filters
6. ✅ **Data pager** — inline `DataPager` component in AuditPage; paginated jobs and logs endpoints
7. ✅ **Silver transform SQL validation** — `_validate_transform_sql` blocks DROP/DELETE/UPDATE/TRUNCATE; enforced on create + execute; upsert pattern in agent system prompt

Deferred:
- Wire up MotherDuck (when moving beyond local DuckDB)

Bug fixes applied (session 2025-03):
- Migration comment-stripping bug in `db/init.py` (leading `--` lines caused entire statements to be skipped)
- `db/001_core_duckdb.sql` updated to use `connector`/`connector_run` table names directly; migration 002 now uses CTAS+DROP instead of RENAME (DuckDB RENAME blocked by UNIQUE constraint catalog dependencies)
- `audit/router.py`: `rows_affected` → `rows_produced` (transform_run column name)
- `scripts/reset_demo.py`: `/integrations` → `/connectors` paths

## Phase 5 Status (IN PROGRESS)

> Full plan: [`.claude/docs/phase-5-plan.md`](.claude/docs/phase-5-plan.md)

1. ✅ **JWT auth** — `POST /api/v1/auth/login`, `/auth/refresh`, `/auth/me`; HS256 tokens; PBKDF2-SHA256 password hashing; `src/auth/jwt.py` + `src/auth/router.py`
2. ✅ **Demo mode** — `DEMO_MODE=true` (default) keeps `admin-token`/`analyst-token`/`viewer-token` working alongside real JWTs; `src/auth/middleware.py` updated
3. ✅ **Admin user seeded** — demo users (`admin@acme.io`, `analyst@acme.io`, `viewer@acme.io`) get `password_hash` set on bootstrap; password `admin123` (dev default via `ADMIN_PASSWORD` env)
4. ✅ **LoginPage** — `apps/dashboard/src/pages/LoginPage.tsx`; demo credential quick-fill buttons; JWT stored in localStorage
5. ✅ **Protected routes** — `RequireAuth` wrapper in `App.tsx`; redirects to `/login` if no token; `LogoutButton` in sidebar
6. ✅ **Token refresh** — 401 responses trigger silent refresh via `_tryRefresh()` in `api.ts`; on failure clears tokens and user gets "Session expired" error

7. ✅ **Tenant configuration** — `GET/PATCH /api/v1/tenant/config`; `platform.tenant_config` table (migration `005_tenant.sql`); `TenantConfigPage.tsx` (LLM provider/model, PII toggle, limits); admin-only sidebar entry
8. ✅ **Tenant user administration** — `GET/POST /api/v1/tenant/users`, `PATCH .../role`, `DELETE .../{id}` (soft-revoke via `revoked_at`); `TenantUsersPage.tsx` (table, inline role edit, add-user modal); admin-only sidebar entry

Deferred (Phase 5 remaining):
- Invite-by-email flow (requires SMTP / Mailpit wiring)
- Schema-per-tenant data segregation
- MotherDuck multi-database path

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
│       │       ├── ConnectorsPage.tsx
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
