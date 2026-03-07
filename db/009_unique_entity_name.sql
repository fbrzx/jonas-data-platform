-- 009: Unique entity name per tenant + layer
-- Prevents duplicate entity names within the same tenant and layer.

-- Remove any existing duplicates first (keep the earliest created row)
DELETE FROM catalogue.entity
WHERE id IN (
    SELECT id FROM (
        SELECT id,
               ROW_NUMBER() OVER (PARTITION BY tenant_id, name, layer ORDER BY created_at) AS rn
        FROM catalogue.entity
    ) sub
    WHERE rn > 1
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_entity_tenant_name_layer
    ON catalogue.entity (tenant_id, name, layer);
