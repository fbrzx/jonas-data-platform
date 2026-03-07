# Jonas Data Platform — Roadmap

## What's Done (Phases 1–6)

| Phase | Summary |
|-------|---------|
| 1 | FastAPI + DuckDB skeleton, DDL, sample data, ingest endpoints |
| 2 | Agent core (multi-provider LLM), schema inference, PII masking, NL-to-SQL |
| 3 | Streaming SSE chat, 14 agent tools, transform CRUD, full React dashboard |
| 4 | Connectors (rename), discover_api, cron scheduler, audit page, jonas-form cards |
| 5 | JWT auth, tenant config/users, invite-by-email, schema-per-tenant |
| 6 | Event-driven transforms, agent memory, code refactoring, JSON skills |

## Priority Assessment

### Why this order matters

The platform works as a demo but has gaps in three areas: **security** (auth is thin, no secrets management), **storage** (locked to local DuckDB), and **observability** (data is there but not visualised). Here's the reasoning:

1. **Security first** — without it, nothing else is production-credible. Multi-tenancy means nothing if tenant boundaries leak.
2. **Storage abstraction second** — unlocks real deployments (MotherDuck, cloud parquet, Postgres metadata). Without this, the platform is a single-machine prototype.
3. **Data visualisation third** — the most visible improvement, but it builds ON secure, multi-backend data. Doing it now means redoing it when storage changes.

That said, a lightweight D3 spike (Phase 8, step 1) can happen early since it only reads from existing query endpoints.

---

## Phase 7 — Security Hardening

**Goal**: Make multi-tenancy real, not just schema separation.

| # | Work Item | Priority | Notes |
|---|-----------|----------|-------|
| 1 | Tenant isolation audit | Critical | Verify every SQL path includes tenant_id; add integration tests that prove cross-tenant access fails |
| 2 | RBAC enforcement gaps | Critical | `core-abstractions.md` defines 5 roles (owner/admin/engineer/analyst/viewer) but code only enforces 3 (admin/analyst/viewer). Add owner + engineer roles |
| 3 | Secrets management | High | `auth_config` currently stores plaintext. Add encrypted-at-rest config (age/sops or env-injected) |
| 4 | Input validation hardening | High | Audit all endpoints for injection (SQL params are good, but check agent tool inputs, transform SQL, connector configs) |
| 5 | Rate limiting | Medium | Per-tenant rate limits on ingest + agent chat |
| 6 | Audit log completeness | Medium | Ensure every mutation is logged (currently partial) |
| 7 | CORS / CSP headers | Medium | Lock down allowed origins |

## Phase 8 — Data Visualisation (D3 / Observable)

**Goal**: Rich, interactive data exploration in the dashboard.

| # | Work Item | Priority | Notes |
|---|-----------|----------|-------|
| 1 | Observable Framework spike | High | Add `@observablehq/plot` to dashboard; build a generic `<DataChart>` component that takes query results and renders bar/line/scatter based on column types |
| 2 | Entity data explorer | High | Replace the flat data table in CataloguePage with an interactive grid + chart toggle. Auto-detect time columns for time-series, categoricals for bar charts |
| 3 | Dashboard stats visualisation | Medium | Replace stat cards on DashboardPage with sparklines (ingest volume over time, transform success rate) |
| 4 | Lineage graph upgrade | Medium | Current LineagePage is a static 3-column layout. Replace with a proper D3 force-directed or dagre DAG with zoom/pan, clickable nodes, edge labels showing transform names |
| 5 | Agent chart responses | Medium | When the agent returns tabular data, offer a "Visualise" button that renders an Observable Plot inline in the chat |
| 6 | Query workbench | Low | Dedicated SQL editor page with results + instant chart, saved queries. Think "DuckDB Studio lite" |

**Recommended library**: `@observablehq/plot` over raw D3. It's higher-level, handles scales/axes automatically, and produces SVG that works well in React. Use raw D3 only for the lineage DAG where you need full layout control.

## Phase 9 — Storage Abstraction

**Goal**: Decouple from local DuckDB so the platform can run against different backends.

| # | Work Item | Priority | Notes |
|---|-----------|----------|-------|
| 1 | Storage interface | High | Define a `StorageBackend` protocol: `execute_sql`, `read_table`, `write_table`, `list_schemas`. Current DuckDB code becomes `LocalDuckDBBackend` |
| 2 | MotherDuck backend | High | `MotherDuckBackend` — connects via `md:` protocol. Schema-per-tenant already works; needs connection pooling and error handling for cloud latency |
| 3 | Metadata in Postgres | Medium | Move platform/catalogue/audit tables to Postgres (the operational store). Keep DuckDB/MotherDuck for analytical queries only. This is the "right" architecture but a bigger lift |
| 4 | Cloud parquet paths | Medium | Change `PARQUET_ROOT` to support `s3://` and `gs://` prefixes. DuckDB handles this natively with httpfs extension |
| 5 | Connection management | Medium | Per-tenant connection pooling, connection health checks, graceful failover |
| 6 | Database-per-tenant (MotherDuck) | Low | Currently schema-per-tenant. For true isolation, each tenant gets `md:tenant_{slug}`. Deferred because schema-per-tenant is sufficient for most use cases |

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

- [ ] Fix `docs/` to reflect reality (Phase 7 prerequisite — done in this session)
- [ ] Add `@observablehq/plot` and build one chart component (1-2 hours)
- [ ] Add owner/engineer roles to RBAC (code change, not architectural)
- [ ] Tenant isolation integration tests (high value, low effort)

## LLM Provider Notes

Current providers: OpenAI, Google (Gemini), Ollama (local).
- Ollama with small models (qwen3:1.7b) needs the Phase 6 defensive tool handling — `.get()` fallbacks, char limits, context pruning
- qwen3.5:cloud via Ollama may work better for complex tool-use flows
- Provider abstraction is already in place (`LLM_PROVIDER` + `LLM_MODEL` env vars)
