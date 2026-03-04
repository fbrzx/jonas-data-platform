-- ============================================================
-- JONAS DATA PLATFORM — Core DDL
-- ============================================================
-- Design principles:
--   1. UUIDs everywhere — no sequential IDs leaking tenant info
--   2. Tenant isolation via FK + RLS policies (added separately)
--   3. JSONB for extensible config — avoids schema rigidity
--   4. Audit trail on all mutations
--   5. Approval gates on transforms & integrations
--   6. Parquet paths derived from: {storage_prefix}/{namespace}/{entity}/{layer}/
-- ============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- TENANCY & IDENTITY
-- ============================================================

CREATE TABLE tenant (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug        TEXT NOT NULL UNIQUE,           -- url-safe, used in paths
    name        TEXT NOT NULL,
    config      JSONB NOT NULL DEFAULT '{}',    -- quotas, feature flags
    storage_prefix TEXT NOT NULL,               -- e.g. "tenants/acme" for parquet root
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- User accounts — auth is external (OAuth/OIDC), this is the internal record
CREATE TABLE user_account (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email        TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Membership binds users to tenants with a role
-- Roles: owner > admin > engineer > analyst > viewer
-- Scope (optional JSONB) can restrict to specific namespaces
CREATE TABLE tenant_membership (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id),
    user_id     UUID NOT NULL REFERENCES user_account(id),
    role        TEXT NOT NULL CHECK (role IN ('owner','admin','engineer','analyst','viewer')),
    scope       JSONB DEFAULT NULL,             -- {"namespaces": ["sales"]}
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by  UUID REFERENCES user_account(id),
    UNIQUE (tenant_id, user_id)
);

-- ============================================================
-- SCHEMA CATALOGUE
-- Namespaces group entities within a tenant (like schemas in a DB)
-- Entities represent tables/views at each medallion layer
-- Fields are the column definitions — versioned via entity.version
-- ============================================================

CREATE TABLE namespace (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id),
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  UUID NOT NULL REFERENCES user_account(id),
    UNIQUE (tenant_id, name)
);

CREATE TABLE entity (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    namespace_id    UUID NOT NULL REFERENCES namespace(id),
    name            TEXT NOT NULL,
    layer           TEXT NOT NULL CHECK (layer IN ('bronze','silver','gold')),
    storage_format  TEXT NOT NULL CHECK (storage_format IN ('parquet','view','materialised')),
    description     TEXT,
    version         INT NOT NULL DEFAULT 1,
    meta            JSONB DEFAULT '{}',     -- tags, SLA, freshness_target_minutes
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by      UUID NOT NULL REFERENCES user_account(id),
    UNIQUE (namespace_id, name, layer)      -- same name allowed across layers
);

-- Parquet path convention (computed, not stored):
--   {tenant.storage_prefix}/{namespace.name}/{entity.name}/{entity.layer}/
--   e.g. tenants/acme/sales/orders/bronze/2025/03/04/part-0001.parquet

CREATE TABLE entity_field (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id   UUID NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    data_type   TEXT NOT NULL CHECK (data_type IN (
                    'string','int','float','bool','timestamp','json','array'
                )),
    nullable    BOOLEAN NOT NULL DEFAULT true,
    is_pii      BOOLEAN NOT NULL DEFAULT false,  -- drives masking in queries
    description TEXT,
    ordinal     INT NOT NULL,                    -- display/storage order
    created_by  UUID NOT NULL REFERENCES user_account(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (entity_id, name)
);

-- ============================================================
-- TRANSFORMS — the medallion layer transitions
-- A transform takes a source entity and produces a target entity
-- Can be SQL, Python, or a dbt model reference
-- Approval gate: approved_by must be set before status=active
-- ============================================================

CREATE TABLE transform (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id         UUID NOT NULL REFERENCES tenant(id),
    name              TEXT NOT NULL,
    source_entity_id  UUID NOT NULL REFERENCES entity(id),
    target_entity_id  UUID NOT NULL REFERENCES entity(id),
    transform_type    TEXT NOT NULL CHECK (transform_type IN ('sql','python','dbt_ref')),
    definition        TEXT NOT NULL,               -- SQL body, python code, or dbt ref
    schedule          TEXT,                        -- cron expression; NULL = event-driven
    status            TEXT NOT NULL DEFAULT 'draft'
                      CHECK (status IN ('draft','active','paused','failed')),
    created_by        UUID NOT NULL REFERENCES user_account(id),
    approved_by       UUID REFERENCES user_account(id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_run_at       TIMESTAMPTZ,
    UNIQUE (tenant_id, name)
);

CREATE TABLE transform_run (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transform_id    UUID NOT NULL REFERENCES transform(id),
    status          TEXT NOT NULL CHECK (status IN ('running','success','failed')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    rows_produced   BIGINT,
    error_detail    JSONB
);

-- Lineage connects entities through transforms
CREATE TABLE entity_lineage (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_entity_id  UUID NOT NULL REFERENCES entity(id),
    target_entity_id  UUID NOT NULL REFERENCES entity(id),
    transform_id      UUID REFERENCES transform(id),  -- NULL for manual lineage
    lineage_type      TEXT NOT NULL CHECK (lineage_type IN (
                          'derived','aggregated','filtered','joined'
                      ))
);

-- ============================================================
-- INTEGRATIONS
-- Templates are system-provided blueprints (Webhook, S3, API pull, etc.)
-- Integrations are tenant-specific instances configured from templates
-- The agent helps users compose these from templates
-- ============================================================

CREATE TABLE integration_template (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name              TEXT NOT NULL UNIQUE,
    direction         TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),
    mode              TEXT NOT NULL CHECK (mode IN ('realtime','batch')),
    config_schema     JSONB NOT NULL,            -- JSON Schema defining required config
    transform_template TEXT,                     -- default mapping SQL
    description       TEXT
);

CREATE TABLE integration (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id         UUID NOT NULL REFERENCES tenant(id),
    template_id       UUID REFERENCES integration_template(id),
    name              TEXT NOT NULL,
    direction         TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),
    mode              TEXT NOT NULL CHECK (mode IN ('realtime','batch')),
    status            TEXT NOT NULL DEFAULT 'draft'
                      CHECK (status IN ('draft','active','paused','error')),
    source_config     JSONB NOT NULL DEFAULT '{}',  -- connection details
    sink_config       JSONB NOT NULL DEFAULT '{}',  -- target mapping
    auth_config       JSONB DEFAULT '{}',         -- encrypted credential references
    schedule          TEXT,                       -- cron for batch; NULL for realtime
    target_entity_id  UUID REFERENCES entity(id), -- Bronze entity for inbound
    created_by        UUID NOT NULL REFERENCES user_account(id),
    approved_by       UUID REFERENCES user_account(id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

CREATE TABLE integration_run (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    integration_id  UUID NOT NULL REFERENCES integration(id),
    status          TEXT NOT NULL CHECK (status IN ('running','success','partial','failed')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    records_in      BIGINT DEFAULT 0,
    records_out     BIGINT DEFAULT 0,
    records_rejected BIGINT DEFAULT 0,
    error_detail    JSONB,
    stats           JSONB DEFAULT '{}'           -- bytes transferred, latency, etc.
);

-- ============================================================
-- PERMISSIONS — fine-grained access control
-- Complements the role on tenant_membership with resource-level grants
-- principal_type + principal_id: either a role name or a user UUID
-- resource_id NULL means "all resources of that type within tenant"
-- ============================================================

CREATE TABLE permission_grant (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES tenant(id),
    principal_type  TEXT NOT NULL CHECK (principal_type IN ('role','user')),
    principal_id    TEXT NOT NULL,                -- role name or user UUID
    resource_type   TEXT NOT NULL CHECK (resource_type IN (
                        'namespace','entity','integration','transform'
                    )),
    resource_id     UUID,                        -- NULL = all of type
    action          TEXT NOT NULL CHECK (action IN (
                        'read','write','create','delete','approve','execute'
                    )),
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by      UUID NOT NULL REFERENCES user_account(id)
);

-- Index for permission checks: "can user X do action Y on resource Z?"
CREATE INDEX idx_perm_lookup ON permission_grant (
    tenant_id, principal_type, principal_id, resource_type, action
);

-- ============================================================
-- AUDIT LOG — append-only, immutable record of all mutations
-- Partitioned by tenant + time for scalability
-- ============================================================

CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES tenant(id),
    user_id         UUID REFERENCES user_account(id), -- NULL for system events
    action          TEXT NOT NULL,                     -- create|update|delete|query|approve|execute
    resource_type   TEXT NOT NULL,
    resource_id     UUID,
    detail          JSONB DEFAULT '{}',               -- before/after, query text, etc.
    ip_address      INET,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_tenant_time ON audit_log (tenant_id, created_at DESC);
CREATE INDEX idx_audit_resource ON audit_log (tenant_id, resource_type, resource_id);

-- ============================================================
-- KEY INDEXES for operational queries
-- ============================================================

CREATE INDEX idx_entity_namespace ON entity (namespace_id, layer);
CREATE INDEX idx_entity_field_entity ON entity_field (entity_id, ordinal);
CREATE INDEX idx_transform_tenant ON transform (tenant_id, status);
CREATE INDEX idx_integration_tenant ON integration (tenant_id, status);
CREATE INDEX idx_lineage_source ON entity_lineage (source_entity_id);
CREATE INDEX idx_lineage_target ON entity_lineage (target_entity_id);
