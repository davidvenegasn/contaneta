-- 028_admin_issuer_meta.sql
-- Notas y flag "necesita revisión" por issuer (solo admin).

CREATE TABLE IF NOT EXISTS admin_issuer_meta (
  issuer_id INTEGER PRIMARY KEY,
  admin_notes TEXT,
  needs_review INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);
