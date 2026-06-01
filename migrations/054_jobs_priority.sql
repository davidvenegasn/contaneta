-- 054_jobs_priority.sql
-- Add priority column to jobs table for recent-first sync orchestration.
-- Higher priority = picked first by worker. Default 0 = normal priority.
-- Applied via Python (_safe_add_column) in migrations_runner for idempotency.

-- ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0;
