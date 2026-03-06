-- Migration 007: add trigger_mode and watch_entities to transforms.transform
-- trigger_mode: 'manual' | 'schedule' | 'on_change'
-- watch_entities: JSON array of catalogue entity IDs to watch for changes

ALTER TABLE transforms.transform ADD COLUMN IF NOT EXISTS trigger_mode VARCHAR DEFAULT 'manual';
ALTER TABLE transforms.transform ADD COLUMN IF NOT EXISTS watch_entities JSON DEFAULT '[]';
