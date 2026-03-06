-- Phase 5: Email invite flow

CREATE TABLE IF NOT EXISTS platform.invite (
    id          VARCHAR     PRIMARY KEY,
    tenant_id   VARCHAR     NOT NULL,
    email       VARCHAR     NOT NULL,
    role        VARCHAR     NOT NULL DEFAULT 'analyst',
    token       VARCHAR     NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_by  VARCHAR,
    created_at  TIMESTAMPTZ DEFAULT current_timestamp,
    used_at     TIMESTAMPTZ
);
