-- Migration 011: schema_migration tracking table
-- Records which DDL files have been applied so future migrations can be
-- skipped if already run (idempotent bootstrap without re-executing SQL).

CREATE TABLE IF NOT EXISTS platform.schema_migration (
    filename   VARCHAR PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT now(),
    checksum   VARCHAR   -- SHA-256 of file contents for drift detection
);
