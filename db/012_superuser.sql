-- Migration 012: Super user support
-- Adds platform-level super users who can manage all tenants.

-- Add is_superuser flag to user accounts
ALTER TABLE platform.user_account ADD COLUMN IF NOT EXISTS is_superuser BOOLEAN DEFAULT FALSE;

-- Seed a demo super user account (no tenant membership required)
INSERT INTO platform.user_account (id, email, display_name, password_hash, is_superuser, created_at)
VALUES (
    'user-superuser',
    'superuser@platform.io',
    'Platform Super User',
    NULL,
    TRUE,
    current_timestamp
) ON CONFLICT (id) DO UPDATE SET is_superuser = TRUE;
