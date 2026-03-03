-- Track when password was last changed (for session invalidation)
ALTER TABLE users ADD COLUMN password_changed_at TEXT;
