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
- Phase 4 complete: connectors rename, discover_api, scheduler, audit page, jonas-form
- Phase 5 complete: JWT auth, tenant config/users, invite-by-email, schema-per-tenant
- Phase 6 complete: event-driven transforms, agent memory, code refactoring, JSON skills
- Phase 7 complete: RBAC 5-role model, configurable CORS, tenant isolation tests, rate limiting, audit completeness, secrets-at-rest (Fernet), input validation caps
- Phase 8 complete: audit stats/chart, DataChart in Catalogue, parquet backup, improved lineage, agent error handling, Observable dashboards with live preview
- Phase 9 complete: StorageBackend protocol (LocalDuckDB/MotherDuck), S3/GCS parquet via httpfs, collections, RBAC frontend enforcement
- Phase 10 complete: CI/CD deploy workflow (GHCR, multi-arch), graceful shutdown, structlog structured logging, migration version tracking, query workbench

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

## Phase 6 Status (COMPLETE)

> Full plan: [`.claude/docs/phase-6-plan.md`](.claude/docs/phase-6-plan.md)

1. ✅ **WS1 — Defensive tool handling** — all `tool_input["x"]` → `.get()` + error returns; small LLMs survive missing fields
2. ✅ **WS2 — JSON skills + context pruning** — `agent/skills/json_patterns.py` (4 DuckDB patterns injected when webhook entities exist); `_MAX_SQL_ROWS=20`, `_MAX_PREVIEW_ROWS=10`, `_MAX_TOOL_RESULT_CHARS=4000`; hard char-cap applied at dispatch
3. ✅ **WS3 — Event-driven transforms** — `trigger_mode` ('manual'|'on_change') + `watch_entities` on transform; `transforms/triggers.py` with debounce (30s), cascade cap (5), cycle guard; fires after ingest and transform execution
4. ✅ **WS4 — Agent memory** — `audit.agent_memory` table; `agent/memory.py` (save/recall/forget/decay/prune); 3 new tools; keyword relevance + score decay; injected into system prompt
5. ✅ **WS5 — Code refactoring** — `agent/service.py` 1242 → 198 lines; `agent/prompt.py`, `agent/handlers/` (5 modules), `catalogue/context.py`, `transforms/validation.py`

Migrations: `db/007_trigger_mode.sql`, `db/008_agent_memory.sql`

## Phase 5 Status (COMPLETE)

> Full plan: [`.claude/docs/phase-5-plan.md`](.claude/docs/phase-5-plan.md)

1. ✅ **JWT auth** — `POST /api/v1/auth/login`, `/auth/refresh`, `/auth/me`; HS256 tokens; PBKDF2-SHA256 password hashing; `src/auth/jwt.py` + `src/auth/router.py`
2. ✅ **Demo mode** — `DEMO_MODE=true` (default) keeps `admin-token`/`analyst-token`/`viewer-token` working alongside real JWTs; `src/auth/middleware.py` updated
3. ✅ **Admin user seeded** — demo users (`admin@acme.io`, `analyst@acme.io`, `viewer@acme.io`) get `password_hash` set on bootstrap; password `admin123` (dev default via `ADMIN_PASSWORD` env)
4. ✅ **LoginPage** — `apps/dashboard/src/pages/LoginPage.tsx`; demo credential quick-fill buttons; JWT stored in localStorage
5. ✅ **Protected routes** — `RequireAuth` wrapper in `App.tsx`; redirects to `/login` if no token; `LogoutButton` in sidebar
6. ✅ **Token refresh** — 401 responses trigger silent refresh via `_tryRefresh()` in `api.ts`; on failure clears tokens and user gets "Session expired" error

7. ✅ **Tenant configuration** — `GET/PATCH /api/v1/tenant/config`; `platform.tenant_config` table (migration `005_tenant.sql`); `TenantConfigPage.tsx` (LLM provider/model, PII toggle, limits); admin-only sidebar entry
8. ✅ **Tenant user administration** — `GET/POST /api/v1/tenant/users`, `PATCH .../role`, `DELETE .../{id}` (soft-revoke via `revoked_at`); `TenantUsersPage.tsx` (table, inline role edit, add-user modal); admin-only sidebar entry

9. ✅ **Schema-per-tenant** — `bronze_{tenant_id}`, `silver_{tenant_id}`, `gold_{tenant_id}` schemas; `src/db/tenant_schemas.py` with `layer_schema()`, `inject_tenant_schemas()`, `provision_tenant_schemas()`; all ingest/catalogue/transform/agent service layers updated; schemas provisioned for all tenants on bootstrap
10. ✅ **Invite-by-email** — `platform.invite` table (migration `006_invite.sql`); `POST /api/v1/tenant/users/invite` (email+role only); `POST /api/v1/auth/accept-invite` (token+name+password); Mailpit in docker-compose; `AcceptInvitePage.tsx`; invite modal updated to email-only flow
11. ✅ **MotherDuck** — already supported via `MOTHERDUCK_TOKEN` env; schema-per-tenant approach works identically; database-per-tenant path deferred to Phase 7

## Phase 7 Status (COMPLETE)

> Security hardening

1. ✅ **5-tier RBAC model** — `auth/permissions.py` now defines all five roles: `owner > admin > engineer > analyst > viewer`; demo tokens: `owner-token`, `engineer-token` added
2. ✅ **Configurable CORS origins** — `CORS_ORIGINS` env var (comma-separated); defaults to `http://localhost:5173`; parsed in `main.py`
3. ✅ **Tenant isolation integration tests** — `services/api/tests/test_tenant_isolation.py`; 13 tests, all green
4. ✅ **Rate limiting** — `src/limiter.py` shared SlowAPI limiter (key=user_id fallback IP); `120/minute` webhook ingest, `20/minute` batch ingest; `SlowAPIMiddleware` in `main.py`
5. ✅ **Audit completeness** — all four ingest endpoints call `write_audit`; page_size capped at 200, days capped at 90 in audit router
6. ✅ **Secrets at rest** — `src/security/crypto.py` (Fernet AES-128-CBC); `CONNECTOR_ENCRYPT_KEY` env var; `integrations/service.py` encrypts config on write, decrypts on read; backward-compat with plaintext
7. ✅ **Input validation caps** — audit endpoints bound page_size (1–200) and days (1–90)

## Phase 8 Status (COMPLETE)

> Data visualisation + Observable dashboards

1. ✅ **`GET /api/v1/audit/stats?days=N`** — `audit/router.py`; per-day connector + transform run counts (total/success/error) plus overall totals
2. ✅ **`ActivityChart` SVG component** — `apps/dashboard/src/components/ActivityChart.tsx`; inline SVG dual-bar chart; full-bleed layout in DashboardPage (renamed "Overview")
3. ✅ **`DataChart` Observable Plot component** — `apps/dashboard/src/components/DataChart.tsx`; auto-selects chart type (time-series / bar / scatter / histogram); table/chart toggle in CataloguePage
4. ✅ **Parquet backup storage** — `src/storage/parquet.py`; tenant-scoped directory layout (`{tenant}/{layer}/{entity}/`); called after every ingest and transform execution; designed as future primary store
5. ✅ **Improved lineage arrowheads** — `markerEnd` only attached when edge is visible (not on dimmed edges)
6. ✅ **Agent error surfacing** — SSE stream catches LLM errors (429 rate limit, 401 auth, 503 overload) and returns user-friendly messages instead of generic "Internal server error"
7. ✅ **Observable Framework dashboards** — `src/dashboards/` module; `GET/PUT/DELETE /api/v1/dashboards/{slug}`; `GET/PUT /api/v1/dashboards/_config`; agent `create_dashboard` tool generates `.md` files; `DashboardsPage.tsx` with sidebar list, edit/preview toggle, live chart rendering (Observable Plot + `@observablehq/inputs`), and shared `jonas.config.js` (API URL never in .md files)
8. ✅ **Dashboard live preview** — `js` blocks parsed and executed in-browser; `jonasPreview()` data loader blocks fetch from API; `Plot.plot()`/`Inputs.table()` cells render real charts; import/setup blocks hidden; graceful error fallback to code display

Key files:
- `services/api/src/dashboards/service.py` — file CRUD, config read/write
- `services/api/src/dashboards/router.py` — REST endpoints
- `services/api/src/agent/handlers/dashboards.py` — `create_dashboard` tool handler + `jonas.config.js` template
- `apps/dashboard/src/pages/DashboardsPage.tsx` — list, editor, live preview renderer

## Phase 10 Status (COMPLETE)

> Production readiness

1. ✅ **CI/CD deploy workflow** — `.github/workflows/deploy.yml`; triggers on push to main/master or semver tag; builds multi-arch Docker image (amd64+arm64) and pushes to GHCR; includes lint+test gate and step summary
2. ✅ **Graceful shutdown** — `uvicorn --timeout-graceful-shutdown 10` in Dockerfile CMD; in-flight requests drain before SIGTERM kills the process
3. ✅ **Structured logging (structlog)** — `src/logging_config.py`; JSON output by default (LOG_FORMAT=json), coloured text in dev (LOG_FORMAT=text); all key log calls use `structlog.get_logger()` with contextual key-value pairs
4. ✅ **Migration version tracking** — `platform.schema_migration` table (migration 011); `bootstrap()` records filename + SHA-256 checksum of each applied migration; skips already-applied migrations on restart
5. ✅ **Query Workbench** — `POST /api/v1/query` (SELECT-only, role-scoped layer access, 500-row cap); `GET /api/v1/query/tables` (table browser for autocomplete); `QueryWorkbenchPage.tsx` with SQL editor (Tab→indent, Ctrl+Enter→run), table browser sidebar, results table, chart toggle

Key files:
- `services/api/src/logging_config.py` — structlog setup
- `services/api/src/query/router.py` — query workbench backend
- `apps/dashboard/src/pages/QueryWorkbenchPage.tsx` — SQL editor UI
- `.github/workflows/deploy.yml` — Docker build + push workflow
- `db/011_migration_tracking.sql` — schema_migration DDL

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

**Demo tokens (hardcoded for local dev, DEMO_MODE=true)**
```
owner-token    → role: owner    (tenant super-admin; all permissions incl. user approve)
admin-token    → role: admin    (full layer access + PII; all permissions except user approve)
engineer-token → role: engineer (approve transforms/connectors/catalogue; no user admin)
analyst-token  → role: analyst  (silver/gold only, PII masked; read/write, no approve)
viewer-token   → role: viewer   (gold only, PII masked; read-only)
```

**Data volumes (local)**
```
data/db/jonas.duckdb   ← DuckDB file (git-ignored)
data/parquet/          ← parquet storage (git-ignored)
```
