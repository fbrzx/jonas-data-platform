# Phase 5 Plan — Auth, Tenant Config & Data Segregation

> Status: **planned, not started** — detail this before implementation begins.

## Overview

Phase 5 replaces the hardcoded demo tokens with real authentication and introduces
full multi-tenancy: each tenant has isolated data, its own admin-managed user roster,
and configuration scoped to its needs. This is the production-readiness phase.

---

## 1. Authentication

Replace `auth/middleware.py` Bearer token lookup with a real identity layer.

### Decision needed: auth strategy

| Option | Notes |
|--------|-------|
| **Managed (Auth0 / Clerk / Supabase Auth)** | Fastest to ship. Handles sessions, MFA, social login. Adds external dependency. |
| **Self-hosted (Keycloak)** | Full control, runs in Docker. Heavier ops. |
| **JWT-only (FastAPI + python-jose)** | Lightweight, no external service. Need to build registration + password reset flows. |

Recommended starting point: **JWT-only** for local/demo, with an adaptor interface so a managed provider can be swapped in later.

### Implementation sketch

**New files:**
- `services/api/src/auth/jwt.py` — encode/decode JWTs (`python-jose`, `passlib`)
- `services/api/src/auth/router.py` — `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`, `POST /api/v1/auth/logout`
- `services/api/src/auth/register.py` — `POST /api/v1/auth/register` (invite-only or open, configurable)

**DB changes:**
- Add `password_hash VARCHAR` to `platform.user_account`
- Add `refresh_token VARCHAR`, `token_expires_at TIMESTAMP` to `platform.user_account`
- Add `platform.invite` table: `(id, tenant_id, email, role, token, expires_at, used_at)`

**Middleware change (`auth/middleware.py`):**
- Decode JWT from `Authorization: Bearer <token>`
- Look up `user_id` from token claims, load user + tenant membership from DB
- Keep demo tokens behind a `DEMO_MODE=true` env flag for local dev

**Dashboard:**
- New `LoginPage.tsx` — email + password form, calls `POST /api/v1/auth/login`, stores JWT in `localStorage`
- Token refresh on 401 responses (interceptor in `api.ts`)
- `LogoutButton` in sidebar
- Protected route wrapper — redirect to `/login` if no valid token

---

## 2. Tenant Configuration (Admin Only)

Admins can view and edit settings that control platform behaviour for their tenant.

### Config surface

Stored in a new `platform.tenant_config` table:
```sql
CREATE TABLE IF NOT EXISTS platform.tenant_config (
    tenant_id VARCHAR NOT NULL,
    key VARCHAR NOT NULL,
    value JSON NOT NULL,
    updated_by VARCHAR,
    updated_at TIMESTAMP DEFAULT now(),
    PRIMARY KEY (tenant_id, key)
);
```

**Config keys (v1):**
| Key | Type | Description |
|-----|------|-------------|
| `llm_provider` | string | Override global LLM provider for this tenant |
| `llm_model` | string | Override model |
| `allowed_layers` | array | Which layers are exposed to the tenant |
| `pii_masking_enabled` | bool | Toggle PII masking (default true) |
| `max_connector_runs_per_day` | int | Rate limit on scheduled pulls |
| `data_retention_days` | int | How long bronze records are kept |

**API:**
- `GET /api/v1/tenant/config` — admin only
- `PATCH /api/v1/tenant/config` — admin only, partial update

**Dashboard:**
- New `TenantConfigPage.tsx` — form rendered from config schema, admin-gated
- Accessible from sidebar (admin role only)

---

## 3. Tenant User Administration (Admin Only)

Admins can invite users, assign roles, and revoke access within their tenant.

### User management flows

- **Invite**: admin enters email + role → system creates `platform.invite` record → sends email (via Mailpit in dev, SMTP in prod) with a one-time link → user sets password → membership created
- **Role change**: admin updates `platform.tenant_membership.role`
- **Revoke**: soft-delete membership (`revoked_at` timestamp); JWT validation checks membership is active

**API:**
- `GET /api/v1/tenant/users` — list tenant members (admin only)
- `POST /api/v1/tenant/users/invite` — create invite + send email
- `PATCH /api/v1/tenant/users/{user_id}/role` — change role
- `DELETE /api/v1/tenant/users/{user_id}` — revoke access
- `POST /api/v1/auth/accept-invite` — public; accepts invite token, creates user + membership

**Dashboard:**
- New `TenantUsersPage.tsx` — table of members with role badges, invite button (opens modal), revoke button
- Accessible from sidebar (admin role only)

---

## 4. Tenant Data Segregation

Currently `tenant_id` is passed in queries but all data lives in the same DuckDB schemas. Phase 5 enforces true isolation.

### Isolation strategy: schema-per-tenant

Each tenant gets dedicated schemas:
```
bronze_<tenant_id>/
silver_<tenant_id>/
gold_<tenant_id>/
```

**Migration path:**
- `db/init.py` creates tenant schemas on first login/provisioning
- All service queries replace hardcoded `bronze.`, `silver.`, `gold.` with `bronze_{tenant_id}.` etc.
- Agent system prompt and SQL scope checker updated to use tenant-scoped schema names
- `run_sql` tool prefixes bare layer references with the tenant schema

**Catalogue/transform/integration isolation:**
All tables already have `tenant_id` columns — no structural change needed. The schema-per-tenant change is purely about the physical data lake schemas (bronze/silver/gold).

### MotherDuck path

When switching to MotherDuck, isolation becomes database-per-tenant:
```
md:<tenant_id>_bronze
md:<tenant_id>_silver
md:<tenant_id>_gold
```
Connection pool maintains one connection per active tenant database.

### RBAC hardening

- All service functions currently trust the `tenant_id` extracted from the auth token — this is correct but must be audited for every endpoint
- Add integration test suite: confirm that tenant A cannot read tenant B's entities, bronze data, transforms, or connector configs even with a valid token
- Rate-limit agent chat per tenant (token budget / minute)

---

## Open Questions to Resolve Before Starting

1. **Auth provider choice** — managed vs self-hosted vs JWT-only (recommendation: JWT-only first)
2. **Invite flow** — open registration or invite-only? (recommendation: invite-only for a B2B platform)
3. **Tenant provisioning** — self-serve signup or admin-created tenants? (recommendation: admin-created for v1)
4. **Schema-per-tenant vs database-per-tenant** — DuckDB file vs MotherDuck path (resolve before migration)
5. **Session storage** — `localStorage` (simple, XSS risk) vs `httpOnly` cookie (safer, CORS setup needed)
6. **Password policy** — minimum length, complexity, bcrypt rounds
7. **MFA** — out of scope for v1 or required?

---

## Implementation Sequence (to be refined)

| Step | Work |
|------|------|
| 1 | DB: `password_hash`, `invite`, `tenant_config`, `tenant_member.revoked_at` |
| 2 | Auth: JWT encode/decode, login/refresh/logout endpoints |
| 3 | Middleware: JWT validation, demo-mode flag |
| 4 | Dashboard: LoginPage, protected routes, token refresh |
| 5 | Invite flow: API + email sending + accept endpoint |
| 6 | TenantUsersPage (admin) |
| 7 | TenantConfigPage (admin) |
| 8 | Schema-per-tenant migration in init.py + all service layers |
| 9 | RBAC audit + cross-tenant isolation tests |
| 10 | MotherDuck multi-database path (if applicable) |
