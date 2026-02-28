-- 027_notifications.sql
-- Motor simple de notificaciones (Home).

CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'info',   -- info|warning|danger
  action_url TEXT,
  dedupe_key TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  read_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_dedupe ON notifications(issuer_id, dedupe_key);
CREATE INDEX IF NOT EXISTS idx_notifications_issuer_read ON notifications(issuer_id, read_at, created_at);

