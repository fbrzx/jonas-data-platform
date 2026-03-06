-- ============================================================
-- JONAS DATA PLATFORM — Core DDL (DuckDB / MotherDuck)
-- ============================================================
-- Adapted from 001_core.sql (PostgreSQL) with these changes:
--   • No uuid-ossp / pgcrypto extensions → gen_random_uuid()
--   • JSONB → JSON  (DuckDB has JSON but not JSONB)
--   • INET → VARCHAR  (no network type in DuckDB)
--   • TIMESTAMPTZ → TIMESTAMPTZ  (supported in DuckDB 0.10+)
--   • DEFAULT now() → DEFAULT current_timestamp
--   • FK constraints declared but NOT enforced by DuckDB
--   • Tables split across named schemas to match service code:
--       platform    — tenant, user_account, tenant_membership
--       catalogue   — namespace, entity, entity_field
--       transforms  — transform, transform_run, entity_lineage
--       integrations — integration_template, connector, connector_run
--       permissions — permission_grant
--       audit       — audit_log
-- ============================================================

-- ============================================================
-- SCHEMAS
-- ============================================================

CREATE SCHEMA IF NOT EXISTS platform;
CREATE SCHEMA IF NOT EXISTS catalogue;
CREATE SCHEMA IF NOT EXISTS transforms;
CREATE SCHEMA IF NOT EXISTS integrations;
CREATE SCHEMA IF NOT EXISTS permissions;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;

-- ============================================================
-- TENANCY & IDENTITY  (platform schema)
-- ============================================================

CREATE TABLE IF NOT EXISTS platform.tenant (
    id             VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    slug           VARCHAR NOT NULL UNIQUE,
    name           VARCHAR NOT NULL,
    config         JSON    NOT NULL DEFAULT '{}',
    storage_prefix VARCHAR NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS platform.user_account (
    id           VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    email        VARCHAR NOT NULL UNIQUE,
    display_name VARCHAR NOT NULL,
    password_hash VARCHAR,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS platform.tenant_membership (
    id         VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  VARCHAR NOT NULL,   -- REFERENCES platform.tenant(id)
    user_id    VARCHAR NOT NULL,   -- REFERENCES platform.user_account(id)
    role       VARCHAR NOT NULL CHECK (role IN ('owner','admin','engineer','analyst','viewer')),
    scope      JSON    DEFAULT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    granted_by VARCHAR,            -- REFERENCES platform.user_account(id)
    UNIQUE (tenant_id, user_id)
);

-- ============================================================
-- SCHEMA CATALOGUE  (catalogue schema)
-- ============================================================

CREATE TABLE IF NOT EXISTS catalogue.namespace (
    id          VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   VARCHAR NOT NULL,  -- REFERENCES platform.tenant(id)
    name        VARCHAR NOT NULL,
    description VARCHAR,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    created_by  VARCHAR NOT NULL,  -- REFERENCES platform.user_account(id)
    UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS catalogue.entity (
    id             VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      VARCHAR NOT NULL,  -- denormalised for fast per-tenant queries
    namespace_id   VARCHAR,           -- REFERENCES catalogue.namespace(id)
    name           VARCHAR NOT NULL,
    layer          VARCHAR NOT NULL CHECK (layer IN ('bronze','silver','gold')),
    storage_format VARCHAR NOT NULL DEFAULT 'parquet'
                   CHECK (storage_format IN ('parquet','view','materialised')),
    description    VARCHAR,
    version        INTEGER NOT NULL DEFAULT 1,
    tags           JSON    DEFAULT '[]',
    meta           JSON    DEFAULT '{}',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    created_by     VARCHAR,           -- REFERENCES platform.user_account(id)
    UNIQUE (namespace_id, name, layer)
);

CREATE TABLE IF NOT EXISTS catalogue.entity_field (
    id          VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id   VARCHAR NOT NULL,  -- REFERENCES catalogue.entity(id)
    name        VARCHAR NOT NULL,
    data_type   VARCHAR NOT NULL CHECK (data_type IN (
                    'string','int','float','bool','timestamp','json','array'
                )),
    nullable    BOOLEAN NOT NULL DEFAULT true,
    is_pii      BOOLEAN NOT NULL DEFAULT false,
    description VARCHAR,
    ordinal     INTEGER NOT NULL,
    sample_values JSON DEFAULT '[]',
    created_by  VARCHAR,           -- REFERENCES platform.user_account(id)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    UNIQUE (entity_id, name)
);

-- ============================================================
-- TRANSFORMS  (transforms schema)
-- ============================================================

CREATE TABLE IF NOT EXISTS transforms.transform (
    id               VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        VARCHAR NOT NULL,  -- REFERENCES platform.tenant(id)
    name             VARCHAR NOT NULL,
    description      VARCHAR DEFAULT '',
    source_entity_id VARCHAR,           -- REFERENCES catalogue.entity(id)
    target_entity_id VARCHAR,           -- REFERENCES catalogue.entity(id)
    source_layer     VARCHAR NOT NULL DEFAULT 'bronze',
    target_layer     VARCHAR NOT NULL DEFAULT 'silver',
    transform_sql    VARCHAR NOT NULL DEFAULT '',
    transform_type   VARCHAR NOT NULL DEFAULT 'sql'
                     CHECK (transform_type IN ('sql','python','dbt_ref')),
    schedule         VARCHAR,
    status           VARCHAR NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft','pending_approval','approved','rejected','active','paused','failed')),
    tags             JSON    DEFAULT '[]',
    created_by       VARCHAR,           -- REFERENCES platform.user_account(id)
    approved_by      VARCHAR,           -- REFERENCES platform.user_account(id)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    last_run_at      TIMESTAMPTZ,
    UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS transforms.transform_run (
    id           VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    transform_id VARCHAR NOT NULL,  -- REFERENCES transforms.transform(id)
    status       VARCHAR NOT NULL CHECK (status IN ('running','success','failed')),
    started_at   TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    completed_at TIMESTAMPTZ,
    rows_produced BIGINT,
    error_detail JSON
);

CREATE TABLE IF NOT EXISTS transforms.entity_lineage (
    id               VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    source_entity_id VARCHAR NOT NULL,  -- REFERENCES catalogue.entity(id)
    target_entity_id VARCHAR NOT NULL,  -- REFERENCES catalogue.entity(id)
    transform_id     VARCHAR,           -- REFERENCES transforms.transform(id)
    lineage_type     VARCHAR NOT NULL CHECK (lineage_type IN (
                         'derived','aggregated','filtered','joined'
                     ))
);

-- ============================================================
-- INTEGRATIONS  (integrations schema)
-- ============================================================

CREATE TABLE IF NOT EXISTS integrations.integration_template (
    id               VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    name             VARCHAR NOT NULL UNIQUE,
    direction        VARCHAR NOT NULL CHECK (direction IN ('inbound','outbound')),
    mode             VARCHAR NOT NULL CHECK (mode IN ('realtime','batch')),
    config_schema    JSON    NOT NULL DEFAULT '{}',
    transform_template VARCHAR,
    description      VARCHAR
);

CREATE TABLE IF NOT EXISTS integrations.connector (
    id               VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        VARCHAR NOT NULL,  -- REFERENCES platform.tenant(id)
    template_id      VARCHAR,           -- REFERENCES integrations.integration_template(id)
    name             VARCHAR NOT NULL,
    description      VARCHAR DEFAULT '',
    connector_type   VARCHAR NOT NULL DEFAULT 'webhook',
    direction        VARCHAR NOT NULL DEFAULT 'inbound'
                     CHECK (direction IN ('inbound','outbound')),
    mode             VARCHAR NOT NULL DEFAULT 'realtime'
                     CHECK (mode IN ('realtime','batch')),
    status           VARCHAR NOT NULL DEFAULT 'active'
                     CHECK (status IN ('draft','active','paused','error')),
    config           JSON    NOT NULL DEFAULT '{}',
    source_config    JSON    NOT NULL DEFAULT '{}',
    sink_config      JSON    NOT NULL DEFAULT '{}',
    auth_config      JSON    DEFAULT '{}',
    schedule         VARCHAR,
    cron_schedule    VARCHAR,
    target_entity_id VARCHAR,           -- REFERENCES catalogue.entity(id)
    tags             JSON    DEFAULT '[]',
    created_by       VARCHAR,           -- REFERENCES platform.user_account(id)
    approved_by      VARCHAR,           -- REFERENCES platform.user_account(id)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS integrations.connector_run (
    id               VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_id   VARCHAR NOT NULL,  -- REFERENCES integrations.connector(id)
    status           VARCHAR NOT NULL CHECK (status IN ('running','success','partial','failed')),
    started_at       TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    completed_at     TIMESTAMPTZ,
    records_in       BIGINT DEFAULT 0,
    records_out      BIGINT DEFAULT 0,
    records_rejected BIGINT DEFAULT 0,
    error_detail     JSON,
    stats            JSON DEFAULT '{}'
);

-- ============================================================
-- PERMISSIONS  (permissions schema)
-- ============================================================

CREATE TABLE IF NOT EXISTS permissions.permission_grant (
    id             VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      VARCHAR NOT NULL,  -- REFERENCES platform.tenant(id)
    principal_type VARCHAR NOT NULL CHECK (principal_type IN ('role','user')),
    principal_id   VARCHAR NOT NULL,
    resource_type  VARCHAR NOT NULL CHECK (resource_type IN (
                       'namespace','entity','integration','transform'
                   )),
    resource_id    VARCHAR,
    action         VARCHAR NOT NULL CHECK (action IN (
                       'read','write','create','delete','approve','execute'
                   )),
    granted_at     TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    granted_by     VARCHAR NOT NULL   -- REFERENCES platform.user_account(id)
);

CREATE INDEX IF NOT EXISTS idx_perm_lookup
    ON permissions.permission_grant (tenant_id, principal_type, principal_id, resource_type, action);

-- ============================================================
-- AUDIT LOG  (audit schema)
-- ============================================================

CREATE TABLE IF NOT EXISTS audit.audit_log (
    id            VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     VARCHAR NOT NULL,  -- REFERENCES platform.tenant(id)
    user_id       VARCHAR,           -- NULL for system events
    action        VARCHAR NOT NULL,
    resource_type VARCHAR NOT NULL,
    resource_id   VARCHAR,
    detail        JSON    DEFAULT '{}',
    ip_address    VARCHAR,           -- INET → VARCHAR (DuckDB has no INET type)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE INDEX IF NOT EXISTS idx_audit_tenant_time
    ON audit.audit_log (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_resource
    ON audit.audit_log (tenant_id, resource_type, resource_id);

-- ============================================================
-- OPERATIONAL INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_entity_namespace
    ON catalogue.entity (namespace_id, layer);

CREATE INDEX IF NOT EXISTS idx_entity_field_entity
    ON catalogue.entity_field (entity_id, ordinal);

CREATE INDEX IF NOT EXISTS idx_transform_tenant
    ON transforms.transform (tenant_id, status);

CREATE INDEX IF NOT EXISTS idx_connector_tenant
    ON integrations.connector (tenant_id, status);

CREATE INDEX IF NOT EXISTS idx_lineage_source
    ON transforms.entity_lineage (source_entity_id);

CREATE INDEX IF NOT EXISTS idx_lineage_target
    ON transforms.entity_lineage (target_entity_id);

-- ============================================================
-- SEED: demo tenant + demo users (for local / MotherDuck dev)
-- ============================================================

INSERT INTO platform.tenant (id, slug, name, storage_prefix)
VALUES ('tenant-acme', 'acme', 'Acme Corp', 'tenants/acme')
ON CONFLICT DO NOTHING;

INSERT INTO platform.user_account (id, email, display_name) VALUES
    ('user-admin',   'admin@acme.io',   'Acme Admin'),
    ('user-analyst', 'analyst@acme.io', 'Acme Analyst'),
    ('user-viewer',  'viewer@acme.io',  'Acme Viewer')
ON CONFLICT DO NOTHING;

INSERT INTO platform.tenant_membership (tenant_id, user_id, role) VALUES
    ('tenant-acme', 'user-admin',   'admin'),
    ('tenant-acme', 'user-analyst', 'analyst'),
    ('tenant-acme', 'user-viewer',  'viewer')
ON CONFLICT DO NOTHING;
