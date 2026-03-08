-- Phase 9: Collections — lightweight grouping tag on entities, transforms, connectors.
-- A collection is a VARCHAR label (one per resource, nullable).

ALTER TABLE catalogue.entity       ADD COLUMN IF NOT EXISTS collection VARCHAR;
ALTER TABLE transforms.transform   ADD COLUMN IF NOT EXISTS collection VARCHAR;
ALTER TABLE integrations.connector ADD COLUMN IF NOT EXISTS collection VARCHAR;
