CREATE TABLE IF NOT EXISTS integrations.connector AS
    SELECT *, NULL::VARCHAR AS cron_schedule
    FROM integrations.integration
    WHERE 1=0;

INSERT INTO integrations.connector
    SELECT *, NULL::VARCHAR AS cron_schedule
    FROM integrations.integration
    WHERE id NOT IN (SELECT id FROM integrations.connector);

DROP TABLE IF EXISTS integrations.integration;

CREATE TABLE IF NOT EXISTS integrations.connector_run AS
    SELECT * FROM integrations.integration_run WHERE 1=0;

INSERT INTO integrations.connector_run
    SELECT * FROM integrations.integration_run
    WHERE id NOT IN (SELECT id FROM integrations.connector_run);

DROP TABLE IF EXISTS integrations.integration_run;

CREATE INDEX IF NOT EXISTS idx_connector_tenant
    ON integrations.connector (tenant_id, status);

DROP INDEX IF EXISTS idx_integration_tenant;
