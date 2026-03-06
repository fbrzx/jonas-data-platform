-- Migration 008: agent memory — persistent knowledge store per tenant

CREATE TABLE IF NOT EXISTS audit.agent_memory (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR NOT NULL,
    category VARCHAR NOT NULL,       -- 'routine' | 'solution' | 'preference' | 'context'
    summary VARCHAR NOT NULL,        -- human-readable one-liner
    content JSON NOT NULL,           -- structured detail (SQL patterns, entity refs, etc.)
    relevance_score FLOAT DEFAULT 1.0,
    created_by VARCHAR,
    created_at TIMESTAMP DEFAULT now(),
    last_used_at TIMESTAMP DEFAULT now(),
    use_count INTEGER DEFAULT 0
);
