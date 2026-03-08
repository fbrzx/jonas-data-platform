# Jonas Data Platform — Roadmap

## What's Done (Phases 1–9)

| Phase | Summary |
|-------|---------|
| 1 | FastAPI + DuckDB skeleton, DDL, sample data, ingest endpoints |
| 2 | Agent core (multi-provider LLM), schema inference, PII masking, NL-to-SQL |
| 3 | Streaming SSE chat, 14 agent tools, transform CRUD, full React dashboard |
| 4 | Connectors (rename), discover_api, cron scheduler, audit page, jonas-form cards |
| 5 | JWT auth, tenant config/users, invite-by-email, schema-per-tenant |
| 6 | Event-driven transforms, agent memory, code refactoring, JSON skills |
| 7 | 5-tier RBAC (owner/admin/engineer/analyst/viewer), tenant isolation tests, rate limiting, secrets-at-rest (Fernet), audit completeness, CORS config |
| 8 | Observable dashboards + live preview, DataChart (auto-detect chart type), ActivityChart (SVG dual-bar), parquet backup, lineage arrowheads, agent error surfacing |
| 9 | StorageBackend protocol (LocalDuckDB / MotherDuck), S3/GCS parquet via httpfs, collections (tagging entities/transforms/connectors), RBAC frontend enforcement |

---

## Phase 7 — Security Hardening ✅ COMPLETE

| # | Work Item | Status |
|---|-----------|--------|
| 1 | Tenant isolation tests | ✅ 13 integration tests, all green |
| 2 | 5-tier RBAC (owner/admin/engineer/analyst/viewer) | ✅ Backend + frontend |
| 3 | Secrets at rest | ✅ Fernet AES-128-CBC on connector configs |
| 4 | Input validation hardening | ✅ Page-size caps, SQL blocklist, transform validation |
| 5 | Rate limiting | ✅ SlowAPI — 120/min webhook, 20/min batch |
| 6 | Audit log completeness | ✅ All four ingest endpoints log |
| 7 | CORS config | ✅ `CORS_ORIGINS` env var |

## Phase 8 — Data Visualisation ✅ COMPLETE

| # | Work Item | Status |
|---|-----------|--------|
| 1 | `<DataChart>` — Observable Plot | ✅ Auto-detects time-series / bar / scatter / histogram |
| 2 | Entity data explorer | ✅ Table/chart toggle in CataloguePage |
| 3 | `<ActivityChart>` — dashboard stats | ✅ Dual-bar SVG (connectors + transforms over time) |
| 4 | Observable Framework dashboards | ✅ Full CRUD, live JS/Plot preview, agent `create_dashboard` tool |
| 5 | Lineage arrowheads | ✅ `markerEnd` only on visible edges |
| 6 | Agent chart responses | ↳ Deferred — no "Visualise" button in chat yet |
| 7 | Query workbench | ↳ Deferred to Phase 10 |

## Phase 9 — Storage Abstraction ✅ COMPLETE

| # | Work Item | Status |
|---|-----------|--------|
| 1 | `StorageBackend` protocol | ✅ `LocalDuckDBBackend` + `MotherDuckBackend` |
| 2 | MotherDuck backend | ✅ Connects via `md:`; optional database-per-tenant |
| 3 | Cloud parquet (S3/GCS) | ✅ httpfs; supports MinIO via custom endpoint |
| 4 | Collections | ✅ Tag any entity/transform/connector; CollectionsPage; agent tool |
| 5 | Metadata in Postgres | ↳ Deferred — all metadata stays in DuckDB for now |
| 6 | Per-tenant connection pooling | ↳ Deferred to Phase 10 |

## Phase 10 — Production Readiness

**Goal**: Everything needed to deploy beyond localhost.

| # | Work Item | Notes |
|---|-----------|-------|
| 1 | CI/CD pipeline | GitHub Actions: lint, test, build, deploy |
| 2 | Containerised deployment | Multi-stage Docker, health checks, graceful shutdown |
| 3 | Observability | Structured logging (structlog), metrics (Prometheus), tracing (OpenTelemetry) |
| 4 | Schema migrations | Proper migration tool (alembic-style) instead of DDL-on-boot |
| 5 | Backup / restore | Tenant data export/import, disaster recovery |

---

## Quick Wins (can happen anytime)

- [ ] "Visualise" button in agent chat for tabular results
- [ ] Lineage graph: D3 force-directed or dagre DAG with zoom/pan
- [ ] Query workbench: SQL editor + results + chart (DuckDB Studio lite)
- [ ] Demo personas for owner + engineer (seed scripts)

## LLM Provider Notes

Current providers: OpenAI, Google (Gemini), Ollama (local).
- Ollama with small models (qwen3:1.7b) needs the Phase 6 defensive tool handling — `.get()` fallbacks, char limits, context pruning
- qwen3.5:cloud via Ollama may work better for complex tool-use flows
- Provider abstraction is already in place (`LLM_PROVIDER` + `LLM_MODEL` env vars)
