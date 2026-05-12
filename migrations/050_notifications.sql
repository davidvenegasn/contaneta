-- 050_notifications.sql
-- Add user_id column to notifications table for user-targeted notifications.

ALTER TABLE notifications ADD COLUMN user_id INTEGER;
CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(issuer_id, user_id, read_at);
