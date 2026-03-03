-- 034: Enhance sat_sync_state for auto-sync operations
-- Adds columns for tracking success/error/cooldown per issuer+direction.
-- Idempotent: uses ADD COLUMN IF NOT EXISTS (SQLite 3.35+).

ALTER TABLE sat_sync_state ADD COLUMN IF NOT EXISTS last_success_at TEXT;
ALTER TABLE sat_sync_state ADD COLUMN IF NOT EXISTS last_attempt_at TEXT;
ALTER TABLE sat_sync_state ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE sat_sync_state ADD COLUMN IF NOT EXISTS cooldown_until TEXT;
ALTER TABLE sat_sync_state ADD COLUMN IF NOT EXISTS backfill_days INTEGER DEFAULT 2;
ALTER TABLE sat_sync_state ADD COLUMN IF NOT EXISTS updated_at TEXT;
