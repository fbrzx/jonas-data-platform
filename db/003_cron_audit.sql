-- Migration 003: cron schedule + audit chat tables

-- Add cron schedule column to connectors
ALTER TABLE integrations.connector ADD COLUMN IF NOT EXISTS cron_schedule VARCHAR;

-- Persist agent chat sessions for audit
CREATE TABLE IF NOT EXISTS audit.chat_session (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR NOT NULL,
    user_id VARCHAR NOT NULL,
    started_at TIMESTAMP DEFAULT now(),
    message_count INTEGER DEFAULT 0,
    summary VARCHAR
);

CREATE TABLE IF NOT EXISTS audit.chat_message (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id VARCHAR NOT NULL,
    role VARCHAR NOT NULL,
    content VARCHAR,
    tool_calls JSON,
    created_at TIMESTAMP DEFAULT now()
);
