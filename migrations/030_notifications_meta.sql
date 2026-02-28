-- 030_notifications_meta.sql
-- Add meta_json column for arbitrary metadata on notifications.

ALTER TABLE notifications ADD COLUMN meta_json TEXT;
