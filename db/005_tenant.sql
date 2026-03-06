-- Phase 5: Tenant config and user administration tables

CREATE TABLE IF NOT EXISTS platform.tenant_config (
    tenant_id  VARCHAR NOT NULL,
    key        VARCHAR NOT NULL,
    value      JSON    NOT NULL,
    updated_by VARCHAR,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (tenant_id, key)
);

-- Soft-delete support for tenant membership revocation
ALTER TABLE platform.tenant_membership ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ;
