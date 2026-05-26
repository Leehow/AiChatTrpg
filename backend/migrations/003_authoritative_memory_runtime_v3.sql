-- Authoritative Memory Runtime v3
-- Safe additive migration for existing deployments.

ALTER TABLE trpg_memory_items ADD COLUMN IF NOT EXISTS source_quotes_json JSON NOT NULL DEFAULT '[]';
ALTER TABLE trpg_memory_items ADD COLUMN IF NOT EXISTS identity_scope VARCHAR(40) NOT NULL DEFAULT 'durable_fact';
ALTER TABLE trpg_memory_items ADD COLUMN IF NOT EXISTS reinforcement_count INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS ix_trpg_memory_items_identity_scope
  ON trpg_memory_items (session_id, identity_scope, status);
